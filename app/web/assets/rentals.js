const preview = document.querySelector('#booking-preview');
const previewTitle = document.querySelector('#booking-preview-title');
const previewDescription = document.querySelector('#booking-preview-description');
const previewFacts = document.querySelector('#booking-preview-facts');
document.querySelectorAll('[data-call-service]').forEach(button => {
  button.addEventListener('click', () => {
    previewTitle.textContent = button.dataset.callService;
    previewDescription.textContent = button.dataset.callDescription || 'Call us to check availability and arrange your booking.';
    previewFacts.replaceChildren();
    for (const [label, value] of [['Price', button.dataset.callPrice], ['Booking details', button.dataset.callDuration]]) {
      if (!value) continue;
      const fact = document.createElement('div'); fact.className = 'booking-preview-fact';
      const term = document.createElement('dt'); term.textContent = label;
      const detail = document.createElement('dd'); detail.textContent = value;
      fact.append(term, detail); previewFacts.append(fact);
    }
    preview.showModal();
  });
});
document.querySelectorAll('[data-booking-option]').forEach(button => {
  button.addEventListener('click', () => {
    previewTitle.textContent = button.dataset.bookingOption;
    preview.showModal();
  });
});
preview.querySelector('.dialog-close').addEventListener('click', () => preview.close());
preview.addEventListener('click', event => {
  const box = preview.getBoundingClientRect();
  if (event.target === preview && (event.clientX < box.left || event.clientX > box.right ||
      event.clientY < box.top || event.clientY > box.bottom)) preview.close();
});
