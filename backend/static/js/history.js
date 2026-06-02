document.addEventListener('DOMContentLoaded', async () => {
  const user = await requireAuth();
  if (!user) return;
  const list = document.getElementById('historyList');
  try {
    const notebooks = await api('/notebooks');
    list.innerHTML = notebooks.map(n => `
      <a class="history-row" href="/notebook" data-id="${n.id}">
        <div><strong>${escapeHtml(n.title)}</strong><div class="meta">Última atividade salva no banco local</div></div>
        <span class="btn small">Retomar</span>
      </a>
    `).join('') || '<div class="empty">Nenhuma sessão no histórico.</div>';
    list.querySelectorAll('[data-id]').forEach(a => a.addEventListener('click', () => setNotebookId(a.dataset.id)));
  } catch {
    list.innerHTML = '<div class="empty">Não foi possível carregar histórico. Backend offline.</div>';
  }
});

function escapeHtml(str) {
  return String(str).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}
