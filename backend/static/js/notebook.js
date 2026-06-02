document.addEventListener('DOMContentLoaded', async () => {
  const user = await requireAuth();
  if (!user) return;
  localStorage.removeItem('studyflow_selected_docs');
  setSelectedDocumentIds([]);
  console.log('[NOTEBOOK] Inicializando notebook', state);
  await loadNotebooks();
  await loadDocuments({ force: true });
  if (typeof loadChatHistory === 'function') await loadChatHistory({ force: true });
  updateAgentState('idle', 'Agente pronto', 'Selecione uma ou mais fontes e envie um comando.', 'aguardando');
});

function showToast(message, type = 'ok') {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const div = document.createElement('div');
  div.className = 'toast';
  if (type === 'warn') div.style.background = '#231b09', div.style.color = '#facc15', div.style.borderColor = '#6b5413';
  div.textContent = message;
  document.body.appendChild(div);
  setTimeout(() => div.remove(), 3200);
}

function setStatus(id, text, ok = true) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle('warn', !ok);
}

function updateSelectedCount() {
  const el = document.getElementById('selectedCount');
  if (!el) return;
  const count = state.selectedDocumentIds.length;
  if (count > 0) {
    el.textContent = `${count} selecionada${count === 1 ? '' : 's'}`;
    el.title = 'Fontes marcadas manualmente para o agente.';
    return;
  }
  const docs = Array.isArray(window.availableDocuments) ? window.availableDocuments : [];
  if (docs.length === 1) {
    const name = docs[0].filename || docs[0].original_filename || 'documento recente';
    el.textContent = 'fonte ativa: 1';
    el.title = `Nenhuma caixa marcada. O agente usará a fonte recente: ${name}`;
    return;
  }
  if (docs.length > 1) {
    el.textContent = '0 selecionadas';
    el.title = 'Marque uma ou mais fontes para evitar fallback automático.';
    return;
  }
  el.textContent = '0 selecionadas';
  el.title = 'Nenhuma fonte disponível.';
}

function updateAgentState(kind, title, text, pill) {
  const box = document.getElementById('agentState');
  const stateText = document.getElementById('agentStateText');
  const pillEl = document.getElementById('agentModePill');
  if (!box || !stateText || !pillEl) return;
  box.className = `agent-state ${kind || 'idle'}`;
  box.querySelector('strong').textContent = title || 'Agente pronto';
  stateText.textContent = text || '';
  pillEl.textContent = pill || 'aguardando';
}

async function loadNotebooks() {
  const list = document.getElementById('notebookList');
  if (!list) return;
  try {
    console.log('[NOTEBOOK] Carregando notebooks...');
    const notebooks = await api('/notebooks');
    if (notebooks[0] && !state.notebookId) setNotebookId(notebooks[0].id);
    list.innerHTML = notebooks.map((n, i) => `
      <button class="session-item ${String(state.notebookId) === String(n.id) || (!state.notebookId && i === 0) ? 'active' : ''}" data-id="${n.id}" type="button">
        <div class="item-icon">▤</div>
        <div class="item-text"><strong>${escapeHtml(n.title)}</strong><div class="meta">Hoje · ${new Date().toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'})}</div></div>
      </button>
    `).join('') || '<div class="empty">Nenhuma sessão criada.</div>';

    list.querySelectorAll('[data-id]').forEach(btn => {
      btn.addEventListener('click', async () => {
        console.log('[NOTEBOOK] Selecionando notebook:', btn.dataset.id);
        setNotebookId(btn.dataset.id);
        if (typeof resetChatHistoryState === 'function') resetChatHistoryState();
        await loadNotebooks();
        await loadDocuments({ force: true });
        if (typeof loadChatHistory === 'function') await loadChatHistory({ force: true });
      });
    });
    setStatus('dbStatus', 'Sessão restaurada do banco', true);
  } catch (err) {
    console.error('[NOTEBOOK][ERRO] Falha ao carregar notebooks:', err);
    list.innerHTML = '<div class="meta">Backend offline. Rode o FastAPI.</div>';
    setStatus('dbStatus', 'Backend offline', false);
  }
}

const newNotebookBtn = document.getElementById('newNotebookBtn');
if (newNotebookBtn) {
  newNotebookBtn.addEventListener('click', async () => {
    try {
      console.log('[NOTEBOOK] Criando novo notebook...');
      const nb = await api('/notebooks', { method: 'POST', body: JSON.stringify({ title: 'Novo notebook' }) });
      setNotebookId(nb.id);
      if (typeof resetChatHistoryState === 'function') resetChatHistoryState();
      await loadNotebooks();
      await loadDocuments({ force: true });
      if (typeof loadChatHistory === 'function') await loadChatHistory({ force: true });
      showToast('Novo notebook criado.');
    } catch (err) {
      console.error('[NOTEBOOK][ERRO] Não foi possível criar notebook:', err);
      showToast('Não foi possível criar notebook.', 'warn');
    }
  });
}

// Build 8 - controles mobile: gavetas de PDFs, ações rápidas e menu.
function closeMobilePanels() {
  document.body.classList.remove('mobile-sources-open', 'mobile-actions-open', 'mobile-more-open');
  document.querySelectorAll('[data-mobile-tab]').forEach(btn => btn.classList.remove('active'));
  const overlay = document.getElementById('mobileOverlay');
  if (overlay) overlay.hidden = true;
}

function openMobilePanel(kind) {
  closeMobilePanels();
  if (!kind || kind === 'chat') return;
  document.body.classList.add(`mobile-${kind}-open`);
  const overlay = document.getElementById('mobileOverlay');
  if (overlay) overlay.hidden = false;
  const active = document.querySelector(`[data-mobile-tab="${kind === 'sources' ? 'pdfs' : kind}"]`);
  if (active) active.classList.add('active');
}

document.addEventListener('DOMContentLoaded', () => {
  const overlay = document.getElementById('mobileOverlay');
  const menuBtn = document.getElementById('mobileMenuBtn');
  const closeSourcesBtn = document.getElementById('closeSourcesBtn');
  const closeActionsBtn = document.getElementById('closeActionsBtn');
  const closeMoreBtn = document.getElementById('closeMoreBtn');
  const mobileLogoutBtn = document.getElementById('mobileLogoutBtn');

  closeMobilePanels();
  if (overlay) overlay.addEventListener('click', closeMobilePanels);
  if (menuBtn) menuBtn.addEventListener('click', () => openMobilePanel('more'));
  if (closeSourcesBtn) closeSourcesBtn.addEventListener('click', closeMobilePanels);
  if (closeActionsBtn) closeActionsBtn.addEventListener('click', closeMobilePanels);
  if (closeMoreBtn) closeMoreBtn.addEventListener('click', closeMobilePanels);
  if (mobileLogoutBtn) mobileLogoutBtn.addEventListener('click', logout);

  document.querySelectorAll('[data-mobile-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.mobileTab;
      if (tab === 'chat') return closeMobilePanels();
      if (tab === 'pdfs') return openMobilePanel('sources');
      if (tab === 'actions') return openMobilePanel('actions');
      if (tab === 'more') return openMobilePanel('more');
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeMobilePanels();
  });

  document.querySelectorAll('#quickActionsPanel button[data-prompt]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (window.matchMedia('(max-width: 900px)').matches) closeMobilePanels();
    });
  });
});


// Build 8.1 - segurança extra: se a tela voltar ao modo desktop ou recarregar,
// nenhuma gaveta mobile pode deixar overlay/blur preso por engano.
window.addEventListener('resize', () => {
  if (!window.matchMedia('(max-width: 900px)').matches) closeMobilePanels();
});
window.addEventListener('pageshow', closeMobilePanels);
