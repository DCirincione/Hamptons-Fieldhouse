(() => {
  let config, active = false;
  async function call(path, body) {
    const response = await window.fieldhouseAuth.fetch('/api/square/' + path, {
      method: 'POST', body: JSON.stringify(body || {})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not start checkout.');
    return result;
  }
  async function settings() {
    if (!config) {
      const response = await fetch('/api/square/config', {cache: 'no-store'});
      if (!response.ok) throw new Error('Square checkout is unavailable.');
      config = await response.json();
    }
    return config;
  }
  function statusMessage(message) {
    let status = document.getElementById('square-checkout-status');
    if (!status) {
      status = document.createElement('p');
      status.id = 'square-checkout-status';
      status.className = 'square-checkout-status';
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      document.body.append(status);
    }
    status.textContent = message;
    status.hidden = !message;
  }
  function checkoutLoading(show) {
    let overlay = document.getElementById('square-checkout-loading');
    if (!show) {
      overlay?.remove();
      return;
    }
    if (overlay) return;
    // A native modal dialog enters the browser's top layer, so it can sit above
    // the booking calendar's own modal dialog while Square checkout is prepared.
    overlay = document.createElement('dialog');
    overlay.id = 'square-checkout-loading';
    overlay.className = 'square-checkout-loading';
    overlay.setAttribute('aria-labelledby', 'square-checkout-loading-title');
    overlay.setAttribute('aria-describedby', 'square-checkout-loading-message');
    const card = document.createElement('div');
    card.className = 'square-checkout-loading-card';
    const spinner = document.createElement('span');
    spinner.className = 'square-checkout-spinner';
    spinner.setAttribute('aria-hidden', 'true');
    const title = document.createElement('h1');
    title.id = 'square-checkout-loading-title';
    title.textContent = 'Opening secure checkout';
    const message = document.createElement('p');
    message.id = 'square-checkout-loading-message';
    message.setAttribute('role', 'status');
    message.setAttribute('aria-live', 'polite');
    message.textContent = 'Connecting you to Square. Please keep this page open.';
    card.append(spinner, title, message);
    overlay.append(card);
    document.body.append(overlay);
    overlay.showModal();
  }
  async function open(bookingIds, onLinkReady = () => {}) {
    if (active) return;
    active = true;
    statusMessage('');
    checkoutLoading(true);
    try {
      const cfg = await settings();
      if (!cfg.enabled) throw new Error('Square checkout is not available yet. Your booking remains pending.');
      const result = await call('checkout', {
        request_id: crypto.randomUUID(),
        booking_ids: bookingIds
      });
      const url = new URL(result.checkout_url);
      const allowedHosts = cfg.environment === 'sandbox'
        ? ['sandbox.square.link']
        : ['square.link', 'checkout.square.site'];
      if (url.protocol !== 'https:' || !allowedHosts.includes(url.hostname)) {
        throw new Error('Square returned an invalid secure checkout link. Please contact the Fieldhouse.');
      }
      statusMessage('Redirecting to Square’s secure checkout…');
      onLinkReady(url.href);
      location.assign(url.href);
    } catch (error) {
      checkoutLoading(false);
      statusMessage(error.message || 'Could not start secure checkout. Please try again.');
      active = false;
      throw error;
    }
  }
  async function registerCamp(registration) {
    if (active) return;
    active = true; statusMessage(''); checkoutLoading(true);
    try {
      const cfg = await settings();
      if (!cfg.enabled) throw new Error('Square checkout is not available yet. Your registration has not been submitted.');
      const result = await call('camp-checkout', registration);
      const url = new URL(result.checkout_url);
      const allowedHosts = cfg.environment === 'sandbox' ? ['sandbox.square.link'] : ['square.link', 'checkout.square.site'];
      if (url.protocol !== 'https:' || !allowedHosts.includes(url.hostname)) throw new Error('Square returned an invalid secure checkout link. Please contact the Fieldhouse.');
      statusMessage('Redirecting to Square’s secure checkout…'); location.assign(url.href);
    } catch (error) {
      checkoutLoading(false); statusMessage(error.message || 'Could not start secure checkout. Please try again.'); active = false; throw error;
    }
  }
  window.fieldhouseSquare = {open, settings, reconcile: () => call('reconcile'), registerCamp};
})();
