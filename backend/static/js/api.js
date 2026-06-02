const API_BASE = '/api';

const state = {
  token: localStorage.getItem('studyflow_token') || '',
  userId: localStorage.getItem('studyflow_user_id') || '',
  userName: localStorage.getItem('studyflow_user_name') || '',
  userEmail: localStorage.getItem('studyflow_user_email') || '',
  notebookId: localStorage.getItem('studyflow_notebook_id') || '',
  selectedDocumentIds: [],
  activeFallbackDocumentId: null,
  activeFallbackDocumentName: '',
};

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const token = localStorage.getItem('studyflow_token') || state.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function api(path, options = {}) {
  const bodyIsForm = options.body instanceof FormData;
  const headers = bodyIsForm
    ? authHeaders(options.headers || {})
    : authHeaders({ 'Content-Type': 'application/json', ...(options.headers || {}) });

  console.log('[API] Request:', `${API_BASE}${path}`, { ...options, headers: { ...headers, Authorization: headers.Authorization ? 'Bearer ***' : undefined } });
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const raw = await res.text();
  if (res.status === 401) {
    console.warn('[API][AUTH] Sessão inválida/expirada. Redirecionando para login.');
    clearSession(false);
    if (!['/login', '/register', '/'].includes(window.location.pathname)) window.location.href = '/login';
    throw new Error(raw || 'Sessão inválida.');
  }
  if (!res.ok) {
    console.error('[API][ERRO]', res.status, raw);
    throw new Error(raw || `HTTP ${res.status}`);
  }
  try {
    const json = raw ? JSON.parse(raw) : {};
    console.log('[API] Response:', json);
    return json;
  } catch (err) {
    console.error('[API][JSON][ERRO]', err, raw);
    throw err;
  }
}

function saveSession(payload) {
  const user = payload.user || {};
  state.token = payload.token || '';
  state.userId = String(user.id || '');
  state.userName = user.name || 'Usuário';
  state.userEmail = user.email || '';
  state.notebookId = payload.default_notebook_id ? String(payload.default_notebook_id) : state.notebookId;
  localStorage.setItem('studyflow_token', state.token);
  localStorage.setItem('studyflow_user_id', state.userId);
  localStorage.setItem('studyflow_user_name', state.userName);
  localStorage.setItem('studyflow_user_email', state.userEmail);
  if (state.notebookId) localStorage.setItem('studyflow_notebook_id', state.notebookId);
}

function clearSession(redirect = true) {
  localStorage.removeItem('studyflow_token');
  localStorage.removeItem('studyflow_user_id');
  localStorage.removeItem('studyflow_user_name');
  localStorage.removeItem('studyflow_user_email');
  localStorage.removeItem('studyflow_notebook_id');
  localStorage.removeItem('studyflow_selected_docs');
  state.token = '';
  state.userId = '';
  state.userName = '';
  state.userEmail = '';
  state.notebookId = '';
  state.selectedDocumentIds = [];
  if (redirect) window.location.href = '/';
}

async function requireAuth() {
  const publicPages = ['/', '/login', '/register'];
  if (publicPages.includes(window.location.pathname)) return null;
  if (!state.token) {
    window.location.href = '/login';
    return null;
  }
  try {
    const payload = await api('/auth/me');
    saveSession({ token: state.token, user: payload.user, default_notebook_id: payload.default_notebook_id });
    const nameEls = document.querySelectorAll('[data-user-name]');
    nameEls.forEach(el => { el.textContent = state.userName || 'Usuário'; });
    return payload.user;
  } catch (err) {
    console.error('[AUTH] Falha ao restaurar sessão:', err);
    return null;
  }
}

function setNotebookId(id) {
  const nextId = String(id || '');
  const changed = state.notebookId && state.notebookId !== nextId;
  state.notebookId = nextId;
  state.selectedDocumentIds = [];
  if (state.notebookId) localStorage.setItem('studyflow_notebook_id', state.notebookId);
  localStorage.removeItem('studyflow_selected_docs');
  if (changed && typeof resetChatHistoryState === 'function') resetChatHistoryState();
  updateSelectedCount?.();
}

function setSelectedDocumentIds(ids) {
  state.selectedDocumentIds = [...new Set(ids.map(String).filter(Boolean))];
  localStorage.removeItem('studyflow_selected_docs');
  updateSelectedCount?.();
}

async function logout() {
  try { if (state.token) await api('/auth/logout', { method: 'POST' }); } catch {}
  clearSession(true);
}

document.addEventListener('DOMContentLoaded', () => {
  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) logoutBtn.addEventListener('click', logout);
});
