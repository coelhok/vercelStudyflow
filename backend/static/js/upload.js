const uploadForm = document.getElementById('uploadForm');
const fileInput = document.getElementById('fileInput');
const fileName = document.getElementById('fileName');
const clearSelectionBtn = document.getElementById('clearSelectionBtn');
const MAX_UPLOAD_MB = 10;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

let documentsLoading = false;
let lastDocumentsKey = '';
const deletingDocumentIds = new Set();

if (fileInput) {
  fileInput.addEventListener('change', () => {
    const files = [...(fileInput.files || [])];
    console.log('[UPLOAD] Arquivos selecionados:', files.map(f => ({ name: f.name, size: f.size, type: f.type })));
    if (!files.length) {
      fileName.textContent = 'Escolher PDF, DOCX ou TXT';
      return;
    }
    fileName.textContent = files.length === 1 ? files[0].name : `${files.length} arquivos selecionados`;
  });
}

if (clearSelectionBtn) {
  clearSelectionBtn.addEventListener('click', () => {
    console.log('[UPLOAD] Limpando seleção de documentos');
    setSelectedDocumentIds([]);
    document.querySelectorAll('.doc-check').forEach(el => { el.checked = false; });
    updateDocumentSelectionStyles();
    setStatus('uploadStatus', 'Seleção limpa. O agente usará fallback apenas se necessário.', true);
  });
}

function formatUploadSummary(data) {
  if (data && Array.isArray(data.uploaded)) {
    const ok = data.uploaded.length;
    const errors = Array.isArray(data.errors) ? data.errors.length : 0;
    if (errors) return `${ok} arquivo(s) processado(s), ${errors} com erro`;
    return `${ok} arquivo(s) processado(s)`;
  }
  return `Arquivo salvo: ${data?.chunks || data?.chunk_count || 0} chunks`;
}

function uploadResultNames(data) {
  if (data && Array.isArray(data.uploaded)) {
    return data.uploaded.map(item => item.filename || item.original_filename).filter(Boolean).join(', ');
  }
  return data?.filename || data?.original_filename || 'arquivo';
}


async function uploadFileToSignedUrl(file, signedUrl) {
  const methods = ['PUT', 'POST'];
  let lastError = null;
  for (const method of methods) {
    try {
      console.log('[UPLOAD][DIRECT] Enviando para Supabase Storage:', { method, name: file.name, size: file.size });
      const res = await fetch(signedUrl, {
        method,
        headers: {
          'Content-Type': file.type || 'application/octet-stream',
          'x-upsert': 'true',
        },
        body: file,
      });
      const raw = await res.text().catch(() => '');
      console.log('[UPLOAD][DIRECT] Resposta Storage:', res.status, raw.slice(0, 300));
      if (res.ok) return true;
      lastError = new Error(`Storage ${method} HTTP ${res.status}: ${raw}`);
    } catch (err) {
      lastError = err;
      console.warn('[UPLOAD][DIRECT] Tentativa falhou:', method, err);
    }
  }
  throw lastError || new Error('Falha no upload direto para Storage.');
}

async function uploadSingleFileDirect(file) {
  const prep = await api('/documents/direct-upload-url', {
    method: 'POST',
    body: JSON.stringify({
      notebook_id: state.notebookId,
      filename: file.name,
      file_size: file.size,
      content_type: file.type || 'application/octet-stream',
    }),
  });
  await uploadFileToSignedUrl(file, prep.signed_url);
  return api('/documents/process-storage', {
    method: 'POST',
    body: JSON.stringify({
      notebook_id: state.notebookId,
      storage_path: prep.storage_path,
      original_filename: file.name,
      filename: file.name,
      file_size: file.size,
      content_type: file.type || 'application/octet-stream',
    }),
  });
}

async function uploadFilesDirect(files) {
  const uploaded = [];
  const errors = [];
  for (const file of files) {
    try {
      setStatus('uploadStatus', `Enviando ${file.name} direto ao Storage...`, false);
      updateAgentState('working', 'Upload direto ao Storage', `${file.name}`, 'upload');
      const result = await uploadSingleFileDirect(file);
      if (Array.isArray(result.uploaded)) uploaded.push(...result.uploaded);
      else uploaded.push(result);
      if (Array.isArray(result.errors)) errors.push(...result.errors);
    } catch (err) {
      console.error('[UPLOAD][DIRECT][ERRO]', file.name, err);
      errors.push({ filename: file.name, error: String(err?.message || err), status_code: 500 });
    }
  }
  if (!uploaded.length && errors.length) {
    throw new Error(JSON.stringify({ message: 'Nenhum arquivo foi processado.', errors }));
  }
  const response = { ok: true, uploaded, errors, count: uploaded.length, error_count: errors.length };
  if (uploaded.length === 1) Object.assign(response, uploaded[0]);
  return response;
}

if (uploadForm) {
  uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const files = [...(fileInput.files || [])];
    if (!files.length) return showToast('Selecione um ou mais PDFs, DOCX ou TXT.', 'warn');

    const tooLarge = files.find(file => file.size > MAX_UPLOAD_BYTES);
    if (tooLarge) {
      console.warn('[UPLOAD] Arquivo recusado no frontend por tamanho:', tooLarge.name, tooLarge.size);
      setStatus('uploadStatus', `Arquivo muito grande: ${tooLarge.name}. Limite: ${MAX_UPLOAD_MB} MB`, false);
      updateAgentState('error', 'Arquivo muito grande', `${tooLarge.name} passa de ${MAX_UPLOAD_MB} MB.`, 'erro');
      return showToast(`Arquivo muito grande. Limite: ${MAX_UPLOAD_MB} MB.`, 'warn');
    }

    console.log('[UPLOAD] Iniciando upload múltiplo:', files.map(file => ({ name: file.name, size: file.size, type: file.type })));
    const form = new FormData();
    files.forEach(file => form.append('files', file));
    // Compatibilidade com builds/rotas antigas que esperavam o campo "file".
    if (files.length === 1) form.append('file', files[0]);
    form.append('notebook_id', state.notebookId);

    const submitBtn = uploadForm.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    setStatus('uploadStatus', `Processando ${files.length} arquivo(s)...`, false);
    updateAgentState('working', 'Agente acompanhando upload', `Processando ${files.length} arquivo(s)...`, 'upload');

    try {
      // Build 11.1 Vercel: upload direto para Supabase Storage para evitar 413 FUNCTION_PAYLOAD_TOO_LARGE.
      // Se o fluxo direto falhar em ambiente local antigo, tentamos fallback pelo endpoint multipart tradicional.
      let data;
      try {
        data = await uploadFilesDirect(files);
        console.log('[UPLOAD][DIRECT] Upload/processamento concluído:', data);
      } catch (directErr) {
        console.warn('[UPLOAD][DIRECT] Falhou; tentando fallback multipart tradicional:', directErr);
        const res = await fetch(`${API_BASE}/documents/upload`, {
          method: 'POST',
          headers: authHeaders(),
          body: form,
        });
        const raw = await res.text();
        console.log('[UPLOAD] Resposta bruta:', res.status, raw);
        if (res.status === 401) {
          console.warn('[UPLOAD][AUTH] Sessão expirada durante upload.');
          clearSession(false);
          window.location.href = '/login';
          return;
        }
        if (!res.ok) {
          console.error('[UPLOAD][ERRO]', res.status, raw);
          setStatus('uploadStatus', 'Erro ao salvar arquivo', false);
          updateAgentState('error', 'Erro no upload', 'Não consegui processar esse(s) arquivo(s). Veja o console para detalhes.', 'erro');
          return showToast('Erro ao enviar arquivo.', 'warn');
        }
        data = raw ? JSON.parse(raw) : {};
      }
      console.log('[UPLOAD] Upload concluído:', data);
      fileInput.value = '';
      fileName.textContent = 'Escolher PDF, DOCX ou TXT';
      setSelectedDocumentIds([]);
      setStatus('uploadStatus', formatUploadSummary(data), true);
      await loadDocuments({ force: true });
      updateAgentState('idle', 'Fonte pronta', `${uploadResultNames(data)} processado(s). Marque as fontes quando quiser usar no agente.`, 'pronto');
      const errorCount = Array.isArray(data.errors) ? data.errors.length : 0;
      showToast(errorCount ? `Upload concluído com ${errorCount} erro(s).` : 'Arquivo(s) salvo(s) e processado(s).');
    } catch (err) {
      console.error('[UPLOAD][ERRO] Falha inesperada:', err);
      setStatus('uploadStatus', 'Erro ao salvar arquivo', false);
      updateAgentState('error', 'Erro no upload', 'Falha inesperada no envio do arquivo.', 'erro');
      showToast('Erro ao enviar arquivo.', 'warn');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

function updateDocumentSelectionStyles() {
  document.querySelectorAll('.doc-item').forEach(item => {
    const check = item.querySelector('.doc-check');
    const fallbackActive = !state.selectedDocumentIds.length && document.querySelectorAll('.doc-item').length === 1;
    item.classList.toggle('selected', Boolean(check?.checked));
    item.classList.toggle('fallback-active', Boolean(!check?.checked && fallbackActive));
    const metaSelection = item.querySelector('[data-selection-label]');
    if (metaSelection) metaSelection.textContent = check?.checked ? 'selecionada' : (fallbackActive ? 'ativa' : 'disponível');
  });
  updateSelectedCount();
}

async function deleteDocument(documentId, filename) {
  if (!documentId) return;
  const docKey = String(documentId);
  if (deletingDocumentIds.has(docKey)) {
    console.warn('[UPLOAD] Delete ignorado: documento já está sendo removido:', docKey);
    return;
  }
  const confirmed = confirm(`Remover "${filename}"?

Isso apaga o documento, os chunks e o arquivo no Storage quando existir.`);
  if (!confirmed) return;

  deletingDocumentIds.add(docKey);
  const item = document.querySelector(`.doc-item[data-doc-id="${CSS.escape(docKey)}"]`);
  const btn = item?.querySelector('[data-delete-doc]');
  if (btn) btn.disabled = true;
  if (item) item.classList.add('deleting');
  try {
    console.log('[UPLOAD] Deletando documento:', docKey);
    await api(`/documents/${encodeURIComponent(docKey)}?notebook_id=${encodeURIComponent(state.notebookId)}`, { method: 'DELETE' });
    setSelectedDocumentIds(state.selectedDocumentIds.filter(id => String(id) !== docKey));
    await loadDocuments({ force: true });
    showToast('Documento removido.');
  } catch (err) {
    console.error('[UPLOAD][ERRO] Falha ao deletar documento:', err);
    showToast('Não foi possível remover documento.', 'warn');
    if (item) item.classList.remove('deleting');
    if (btn) btn.disabled = false;
  } finally {
    deletingDocumentIds.delete(docKey);
  }
}

async function loadDocuments(options = {}) {
  const list = document.getElementById('documentList');
  if (!list) return;
  const key = `${state.userId}:${state.notebookId}`;
  if (documentsLoading) {
    console.log('[UPLOAD] loadDocuments ignorado: já existe carregamento em andamento');
    return;
  }
  if (!options.force && lastDocumentsKey === key && list.dataset.loaded === 'true') {
    console.log('[UPLOAD] loadDocuments ignorado: lista já carregada para essa sessão');
    return;
  }

  documentsLoading = true;
  try {
    console.log('[UPLOAD] Carregando documentos...', { userId: state.userId, notebookId: state.notebookId });
    const docs = await api(`/documents?notebook_id=${state.notebookId}`);
    window.availableDocuments = Array.isArray(docs) ? docs : [];
    const existingIds = docs.map(d => String(d.id));
    const validSelected = state.selectedDocumentIds.map(String).filter(id => existingIds.includes(String(id)));
    if (validSelected.length !== state.selectedDocumentIds.length) setSelectedDocumentIds(validSelected);

    list.innerHTML = docs.map(d => {
      const id = String(d.id);
      const checked = state.selectedDocumentIds.map(String).includes(id);
      const fallbackActive = !state.selectedDocumentIds.length && docs.length === 1;
      const statusClass = d.status === 'processed' ? 'ok' : (d.status === 'error' ? 'bad' : 'warn');
      const statusText = d.status === 'processed' ? 'Processado' : (d.status === 'empty' ? 'Sem texto extraído' : d.status);
      const sizeMb = d.file_size ? `${(Number(d.file_size) / 1024 / 1024).toFixed(2)} MB` : 'tamanho n/d';
      const chunkInfo = d.chunk_count ? `${d.chunk_count} chunks` : '0 chunks';
      const storageInfo = d.storage_path ? 'Storage OK' : 'local';
      return `
        <div class="doc-item selectable ${checked ? 'selected' : ''} ${fallbackActive ? 'fallback-active' : ''}" data-doc-id="${escapeHtml(id)}">
          <input class="doc-check" type="checkbox" value="${escapeHtml(id)}" ${checked ? 'checked' : ''} aria-label="Selecionar ${escapeHtml(d.filename)}" />
          <div class="item-icon ${escapeHtml(d.file_type)}">${escapeHtml(d.file_type).toUpperCase()}</div>
          <div class="item-text"><strong title="${escapeHtml(d.filename)}">${escapeHtml(d.filename)}</strong><div class="meta"><span class="dot ${statusClass}"></span>${escapeHtml(statusText)} · ${escapeHtml(sizeMb)} · ${escapeHtml(chunkInfo)} · ${escapeHtml(storageInfo)} · fonte <span data-selection-label>${checked ? 'selecionada' : (fallbackActive ? 'ativa' : 'disponível')}</span></div></div>
          <button class="doc-delete" type="button" data-delete-doc="${escapeHtml(id)}" data-filename="${escapeHtml(d.filename)}" title="Remover documento">Excluir</button>
        </div>
      `;
    }).join('') || '<div class="meta">Nenhum arquivo enviado ainda.</div>';

    list.querySelectorAll('.doc-check').forEach(check => {
      check.addEventListener('change', () => {
        const ids = [...list.querySelectorAll('.doc-check:checked')].map(el => String(el.value));
        console.log('[UPLOAD] Documentos selecionados:', ids);
        setSelectedDocumentIds(ids);
        updateDocumentSelectionStyles();
        setStatus('uploadStatus', `${ids.length} fonte(s) selecionada(s)`, true);
      });
    });

    list.querySelectorAll('[data-delete-doc]').forEach(btn => {
      btn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        deleteDocument(btn.dataset.deleteDoc, btn.dataset.filename || 'documento');
      });
    });

    list.querySelectorAll('.doc-item').forEach(item => {
      item.addEventListener('click', (event) => {
        if (event.target.closest('button')) return;
        if (event.target.classList.contains('doc-check')) return;
        const check = item.querySelector('.doc-check');
        if (!check) return;
        check.checked = !check.checked;
        check.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });

    lastDocumentsKey = key;
    list.dataset.loaded = 'true';
    updateDocumentSelectionStyles();
    setStatus('uploadStatus', docs.length ? `${state.selectedDocumentIds.length} fonte(s) selecionada(s)` : 'Nenhum arquivo enviado', Boolean(docs.length));
  } catch (err) {
    console.error('[UPLOAD][ERRO] Não foi possível carregar documentos:', err);
    list.innerHTML = '<div class="meta">Não foi possível carregar documentos.</div>';
  } finally {
    documentsLoading = false;
  }
}
