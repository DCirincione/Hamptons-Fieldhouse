(() => {
  const noticeKey = 'fh_privacy_notice_v1';
  const preferencesKey = 'fh_accessibility_v1';
  const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const save = (key, value) => { try { localStorage.setItem(key, value); return true; } catch { return false; } };
  const notice = document.getElementById('privacy-notice');
  let noticeOpener = null;
  notice.hidden = read(noticeKey) === 'acknowledged';
  document.querySelectorAll('[data-privacy-open]').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => {
      noticeOpener = button;
      notice.hidden = false;
      document.getElementById('privacy-dismiss').focus();
    });
  });
  document.getElementById('privacy-dismiss').addEventListener('click', () => {
    save(noticeKey, 'acknowledged');
    notice.hidden = true;
    (noticeOpener || document.querySelector('[data-privacy-open]')).focus({preventScroll: true});
  });
  const classes = {largeText: 'a11y-large-text', highContrast: 'a11y-high-contrast', underlineLinks: 'a11y-underline-links', reduceMotion: 'a11y-reduce-motion'};
  let preferences = {};
  try { const stored = JSON.parse(read(preferencesKey)); if (stored && typeof stored === 'object') preferences = stored; } catch { /* Use defaults for invalid storage. */ }
  const controls = document.querySelectorAll('[data-preference]');
  const apply = () => controls.forEach(input => {
    const enabled = preferences[input.dataset.preference] === true;
    input.checked = enabled;
    document.documentElement.classList.toggle(classes[input.dataset.preference], enabled);
  });
  apply();
  controls.forEach(input => input.addEventListener('change', () => {
    preferences[input.dataset.preference] = input.checked;
    apply();
    document.getElementById('preference-status').textContent = save(preferencesKey, JSON.stringify(preferences)) ? 'Settings saved.' : 'Settings applied. This browser could not save them for your next visit.';
  }));
  const dialog = document.getElementById('accessibility-dialog');
  const launcher = document.getElementById('accessibility-launcher');
  launcher.hidden = false;
  launcher.addEventListener('click', () => dialog.showModal());
  document.getElementById('accessibility-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => launcher.focus());
  document.getElementById('accessibility-reset').addEventListener('click', () => {
    preferences = {};
    apply();
    const saved = save(preferencesKey, '{}');
    document.getElementById('preference-status').textContent = saved ? 'Settings reset. Your device’s reduced-motion preference still applies.' : 'Settings reset for this page. This browser could not save the change.';
  });
  const mapButton = document.getElementById('load-map');
  if (mapButton) {
    mapButton.hidden = false;
    mapButton.addEventListener('click', () => {
      const map = document.querySelector('[data-map-src]');
      map.src = map.dataset.mapSrc;
      map.hidden = false;
      document.getElementById('map-placeholder').hidden = true;
      map.focus();
    });
  }
})();
