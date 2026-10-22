(() => {
  let config, sdk, active = false;
  const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents / 100);
  async function call(path, body) {
    const response = await window.fieldhouseAuth.fetch('/api/square/' + path, {method:'POST',body:JSON.stringify(body || {})});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not process payment.');
    return result;
  }
  async function settings() {
    if (!config) {
      const response = await fetch('/api/square/config', {cache:'no-store'});
      if (!response.ok) throw new Error('Square checkout is unavailable.');
      config = await response.json();
    }
    return config;
  }
  async function loadSdk() {
    if (!sdk) sdk = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = config?.environment === 'production'
        ? 'https://web.squarecdn.com/v1/square.js'
        : 'https://sandbox.web.squarecdn.com/v1/square.js';
      script.onload = resolve; script.onerror = () => { sdk = null; reject(new Error('Could not load Square. Please try again.')); };
      document.head.append(script);
    });
    await sdk;
  }
  async function open(bookingIds, onComplete = () => {}) {
    if (active) return;
    active = true;
    let card, submitting = false, attempted = false, paymentBody, opened = true, completed = false;
    // Square's bank-verification window is mounted outside our card form. Native
    // modal dialogs make that window inert, so use a regular accessible overlay.
    const previousFocus = document.activeElement;
    const underlying = [...document.querySelectorAll('dialog[open]')];
    underlying.forEach(dialog => dialog.close());
    const overlay = document.createElement('div'); overlay.className = 'square-payment-overlay';
    const modal = document.createElement('div'); modal.className = 'square-payment-dialog';
    modal.setAttribute('role','dialog'); modal.setAttribute('aria-modal','true');
    modal.setAttribute('aria-labelledby','square-payment-title');
    modal.innerHTML = '<button type="button" class="dialog-close" aria-label="Close payment">×</button><p class="eyebrow square-payment-environment">SECURE PAYMENT WITH SQUARE</p><h2 id="square-payment-title">Pay for your booking</h2><p class="square-payment-total"></p><p>Only the dates included in this payment will be approved automatically.</p><div id="square-card-container"></div><button type="button" class="button square-pay-button" disabled>Loading…</button><p class="square-payment-status" role="status" aria-live="polite"></p>';
    overlay.append(modal); document.body.append(overlay);
    const button = modal.querySelector('.square-pay-button'), status = modal.querySelector('.square-payment-status'), close = modal.querySelector('.dialog-close');
    const cleanup = async () => {
      if (!opened || submitting) return;
      opened = false;
      document.removeEventListener('keydown', keyboard);
      try { if (card) await card.destroy(); }
      catch { /* The SDK may already have removed its frame. */ }
      finally {
        overlay.remove(); active = false;
        if (!completed) {
          underlying.filter(dialog => dialog.isConnected).forEach(dialog => dialog.showModal());
          if (underlying.some(dialog => dialog.id === 'booking-calendar')) document.body.classList.add('booking-modal-open');
        }
        if (completed && underlying.some(dialog => dialog.id === 'booking-calendar')) {
          document.body.classList.remove('booking-modal-open');
          document.querySelector('[data-book-service]')?.focus({preventScroll:true});
        } else if (previousFocus?.isConnected) previousFocus.focus();
      }
    };
    const keyboard = event => {
      if (submitting) return; // Let Square's verification window handle keyboard input.
      if (event.key === 'Escape') { event.preventDefault(); cleanup(); }
      if (event.key === 'Tab') {
        const controls = [...modal.querySelectorAll('button:not([disabled]):not([hidden]), a[href], iframe, input')];
        if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls.at(-1)?.focus(); }
        else if (!event.shiftKey && document.activeElement === controls.at(-1)) { event.preventDefault(); controls[0]?.focus(); }
      }
    };
    document.addEventListener('keydown', keyboard);
    close.onclick = cleanup;
    overlay.addEventListener('click', event => { if (event.target === overlay) cleanup(); });
    close.focus();
    try {
      const cfg = await settings();
      if (!cfg.enabled) throw new Error('Square checkout is not available yet. Your booking remains pending.');
      if (cfg.environment === 'sandbox') modal.querySelector('.square-payment-environment').textContent = 'SQUARE SANDBOX · TEST PAYMENT';
      const quote = await call('quote', {booking_ids:bookingIds});
      if (!opened) return;
      modal.querySelector('.square-payment-total').textContent = `${money(quote.amount_cents)} · ${quote.date_count} date${quote.date_count === 1 ? '' : 's'}`;
      await loadSdk();
      if (!opened) return;
      const payments = window.Square.payments(cfg.application_id, cfg.location_id);
      card = await payments.card();
      if (!opened) { await card.destroy(); return; }
      await card.attach('#square-card-container');
      button.disabled = false; button.textContent = `Pay ${money(quote.amount_cents)}`;
      button.onclick = async () => {
        if (submitting) return;
        submitting = true; button.disabled = true; close.disabled = true;
        status.textContent = 'Processing payment…';
        try {
          if (!paymentBody) {
            const token = await card.tokenize({amount:(quote.amount_cents/100).toFixed(2), billingContact:quote.billing_contact || {}, currencyCode:'USD', intent:'CHARGE', customerInitiated:true, sellerKeyedIn:false});
            if (token.status !== 'OK') throw new Error(token.errors?.map(error => error.message).join(' ') || 'Please check your card details.');
            paymentBody = {request_id:crypto.randomUUID(), source_id:token.token, booking_ids:bookingIds, expected_amount_cents:quote.amount_cents};
          }
          attempted = true;
          const result = await call('pay', paymentBody);
          if (result.status === 'completed') {
            completed = true;
            try { await card.destroy(); } catch { /* Payment is already complete. */ }
            card = null;
            submitting = false;
            modal.classList.add('square-payment-success');
            const environmentLabel = cfg.environment === 'sandbox' ? 'SQUARE SANDBOX · TEST PAYMENT' : 'SECURE PAYMENT WITH SQUARE';
            modal.innerHTML = `<button type="button" class="dialog-close" aria-label="Close confirmation">×</button><div class="square-payment-success-icon" aria-hidden="true">✓</div><p class="eyebrow">${environmentLabel}</p><h2 id="square-payment-title" tabindex="-1">Payment approved!</h2><p class="square-reserved-message"></p><p class="square-payment-total"></p><p>Only the dates covered by this payment are confirmed. Any other unpaid dates still need payment or staff approval.</p><a class="button" href="/account">View My Bookings</a><button type="button" class="staff-utility square-payment-done">Done</button>`;
            modal.querySelector('.square-reserved-message').textContent = quote.date_count === 1
              ? 'Your time is reserved. We’ll see you at the Fieldhouse!'
              : `Your ${quote.date_count} paid dates are reserved. We’ll see you at the Fieldhouse!`;
            modal.querySelector('.square-payment-total').textContent = `${money(quote.amount_cents)} paid · ${quote.date_count} date${quote.date_count === 1 ? '' : 's'} confirmed`;
            modal.querySelector('.dialog-close').onclick = cleanup;
            modal.querySelector('.square-payment-done').onclick = cleanup;
            modal.querySelector('h2').focus();
            try { await onComplete(); }
            catch { /* Confirmation stays visible even if the background refresh fails. */ }
          } else if (result.status === 'failed') {
            paymentBody = null; attempted = false;
            status.textContent = 'The payment was declined. Your dates remain unpaid. Check your card and try again.';
          } else {
            status.textContent = 'Payment is still processing. Check its status before trying another payment.';
          }
        } catch (error) { status.textContent = error.message; }
        finally {
          submitting = false; button.disabled = false; close.disabled = false;
          button.textContent = attempted ? 'Check payment status' : `Pay ${money(quote.amount_cents)}`;
        }
      };
    } catch (error) { status.textContent = error.message; button.hidden = true; }
  }
  window.fieldhouseSquare = {open, settings, reconcile:() => call('reconcile')};
})();
