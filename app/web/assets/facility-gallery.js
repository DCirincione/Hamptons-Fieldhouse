(() => {
  const photos = [...document.querySelectorAll('[data-gallery-photo]')];
  const viewer = document.querySelector('.gallery-viewer');
  if (!viewer || typeof viewer.showModal !== 'function') return;
  const image = viewer.querySelector('.gallery-full-image');
  const caption = viewer.querySelector('.gallery-viewer-caption');
  let current = 0;
  function show(index) {
    current = (index + photos.length) % photos.length;
    image.src = photos[current].href;
    image.alt = photos[current].querySelector('img').alt;
    caption.textContent = `${photos[current].dataset.caption} · ${current + 1} / ${photos.length}`;
  }
  photos.forEach((photo, index) => photo.addEventListener('click', (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    show(index);
    viewer.showModal();
    document.documentElement.classList.add('gallery-is-open');
  }));
  viewer.querySelector('[data-gallery-prev]').addEventListener('click', () => show(current - 1));
  viewer.querySelector('[data-gallery-next]').addEventListener('click', () => show(current + 1));
  viewer.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      show(current + (event.key === 'ArrowLeft' ? -1 : 1));
    }
  });
  viewer.addEventListener('click', (event) => {
    if (event.target === viewer) viewer.close();
  });
  viewer.addEventListener('close', () => document.documentElement.classList.remove('gallery-is-open'));
})();
