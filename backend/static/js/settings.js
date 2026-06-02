document.addEventListener('DOMContentLoaded', async () => { await requireAuth(); });
const form = document.getElementById('settingsForm');
const input = document.getElementById('apiBase');
if (input) input.value = 'API integrada em /api';
if (form) {
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    alert('Nesta build, o frontend e o backend rodam juntos. A API fica em /api.');
  });
}
