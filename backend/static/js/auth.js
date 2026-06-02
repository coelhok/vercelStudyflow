const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');

function setAuthError(message) {
  const el = document.getElementById('authError');
  if (el) el.textContent = message || '';
  else if (message) alert(message);
}

if (loginForm) {
  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    setAuthError('');
    try {
      const payload = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          email: document.getElementById('email').value,
          password: document.getElementById('password').value,
        })
      });
      saveSession(payload);
      window.location.href = '/dashboard';
    } catch (err) {
      console.error('[AUTH][LOGIN][ERRO]', err);
      setAuthError('Login inválido. Verifique e-mail e senha.');
    }
  });
}

if (registerForm) {
  registerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    setAuthError('');
    try {
      const payload = await api('/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          name: document.getElementById('name').value,
          email: document.getElementById('email').value,
          password: document.getElementById('password').value,
        })
      });
      saveSession(payload);
      window.location.href = '/dashboard';
    } catch (err) {
      console.error('[AUTH][REGISTER][ERRO]', err);
      setAuthError('Não foi possível cadastrar. E-mail já usado ou senha curta.');
    }
  });
}
