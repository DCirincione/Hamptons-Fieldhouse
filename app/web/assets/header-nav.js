(() => {
  const menu = document.getElementById('mobile-nav');
  if (!menu) return;
  const summary = menu.querySelector('summary');
  menu.addEventListener('toggle', () => {
    summary.setAttribute('aria-label', menu.open ? 'Close navigation menu' : 'Open navigation menu');
    document.body.classList.toggle('mobile-nav-open', menu.open);
  });
  document.addEventListener('click', event => {
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) { menu.open = false; summary.focus(); }
  });
  matchMedia('(min-width: 761px)').addEventListener('change', event => { if (event.matches) menu.open = false; });
})();
