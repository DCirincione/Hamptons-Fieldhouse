const preview = document.querySelector('#booking-preview');
const previewTitle = document.querySelector('#booking-preview-title');
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
