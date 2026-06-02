document.addEventListener('DOMContentLoaded', async () => {
  const user = await requireAuth();
  if (!user) return;
  await loadDashboard();
});

function escapeHtml(str) {
  return String(str).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function loadDashboard() {
  const nbList = document.getElementById('dashNotebookList');
  const docList = document.getElementById('dashDocumentList');
  try {
    const notebooks = await api('/notebooks');
    const docs = await api('/documents');
    document.getElementById('statNotebooks').textContent = notebooks.length;
    document.getElementById('statDocs').textContent = docs.length;
    nbList.className = '';
    nbList.innerHTML = notebooks.map(n => `
      <a class="notebook-card" href="/notebook" data-id="${n.id}">
        <div><strong>${escapeHtml(n.title)}</strong><div class="meta">Sessão de estudo com IA</div></div>
        <span class="btn small">Abrir</span>
      </a>
    `).join('') || '<div class="empty">Nenhum notebook criado.</div>';
    nbList.querySelectorAll('[data-id]').forEach(a => a.addEventListener('click', () => setNotebookId(a.dataset.id)));

    docList.className = '';
    docList.innerHTML = docs.slice(0,6).map(d => `
      <div class="notebook-card">
        <div style="display:flex;gap:12px;align-items:center"><span class="file-badge">${escapeHtml(d.file_type).toUpperCase()}</span><div><strong>${escapeHtml(d.filename)}</strong><div class="meta">${escapeHtml(d.status)}</div></div></div>
      </div>
    `).join('') || '<div class="empty">Nenhum documento enviado.</div>';
  } catch {
    nbList.innerHTML = '<div class="empty">Backend offline. Rode o FastAPI.</div>';
    docList.innerHTML = '<div class="empty">Sem conexão com API.</div>';
  }
}
