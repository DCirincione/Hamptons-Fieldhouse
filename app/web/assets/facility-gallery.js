(() => {
  const photos = [...document.querySelectorAll('[data-gallery-photo]')];
  const carousel = document.querySelector('.gallery-carousel');
  const viewer = document.querySelector('.gallery-viewer');
  if (!carousel || !viewer || typeof viewer.showModal !== 'function') return;
  function scrollCarousel(direction) {
    const card = photos[0];
    const gap = parseFloat(getComputedStyle(carousel).gap) || 0;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.classList.contains('a11y-reduce-motion');
    carousel.scrollBy({left: direction * (card.getBoundingClientRect().width + gap), behavior: reduceMotion ? 'auto' : 'smooth'});
  }
  document.querySelector('[data-carousel-prev]').addEventListener('click', () => scrollCarousel(-1));
  document.querySelector('[data-carousel-next]').addEventListener('click', () => scrollCarousel(1));
  const image = viewer.querySelector('.gallery-full-image');
  const caption = viewer.querySelector('.gallery-viewer-caption');
  let current = 0;
  function show(index) {
    current = (index + photos.length) % photos.length;
    image.src = photos[current].href;
    image.alt = photos[current].querySelector('img').alt;
    caption.textContent = `${current + 1} / ${photos.length}`;
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
