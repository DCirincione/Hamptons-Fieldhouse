const form = document.querySelector('#contact-form');
const status = document.querySelector('#contact-status');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  const data = Object.fromEntries(new FormData(form));
  for (const key of Object.keys(data)) data[key] = data[key].trim();
  if (Object.values(data).some(value => !value)) {
    status.textContent = 'Please fill in all fields.';
    return;
  }
  button.disabled = true;
  form.setAttribute('aria-busy', 'true');
  status.textContent = 'Sending your message…';
  try {
    const response = await fetch('/api/contact-messages', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data), signal: AbortSignal.timeout(15000),
    });
    const result = await response.json();
    if (!response.ok) {
      status.textContent = response.status === 422
        ? 'Please check your email and phone number, and make sure all fields are filled in.'
        : 'We couldn’t save your message. Please try again or email us directly.';
      return;
    }
    status.textContent = result.message;
    form.reset();
  } catch {
    status.textContent = 'We couldn’t confirm delivery. Please try again or email us directly.';
  } finally {
    button.disabled = false;
    form.removeAttribute('aria-busy');
  }
});
