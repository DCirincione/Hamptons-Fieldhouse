(() => {
  const $ = id => document.getElementById(id);
  let view = 'upcoming', offset = 0, timer = null, active = false, generation = 0, loading = false, cancelling = false;
  const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents/100);
  const date = value => new Date(value).toLocaleString('en-US', {timeZone:'America/New_York',dateStyle:'medium',timeStyle:'short'});
  function sessionExpired() {
    active = false; generation++; clearInterval(timer);
    $('my-bookings-list').replaceChildren(); $('account-summary').hidden = true;
    window.fieldhouseAuth.reload();
  }
  async function loadBookings(quiet = false) {
    if (!active || cancelling || (quiet && loading)) return;
    const current = ++generation;
    loading = true;
    if (!quiet) $('my-bookings-status').textContent = 'Loading your bookings…';
    try {
      const response = await window.fieldhouseAuth.fetch(`/api/bookings/mine?view=${view}&offset=${offset}`);
      if (current !== generation) return;
      if (response.status === 401) { sessionExpired(); return; }
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not load your bookings.');
      const cards = data.bookings.map(booking => {
        const card = document.createElement('article'); card.className = 'customer-booking';
        const top = document.createElement('div'); top.className = 'customer-section-heading';
        const title = document.createElement('h3'); title.textContent = booking.name;
        const status = document.createElement('span'); status.className = `booking-state booking-state-${booking.status}`;
        status.textContent = {pending:'Pending approval',confirmed:'Approved',cancelled:'Cancelled'}[booking.status] || booking.status;
        top.append(title, status);
        const times = document.createElement('p'); times.textContent = `${date(booking.starts_at)} – ${date(booking.ends_at)} Eastern`;
        const info = document.createElement('p'); info.textContent = `${money(booking.total_price_cents)} · ${booking.payment_method === 'venmo' ? 'Venmo' : booking.payment_method === 'cash' ? 'Cash' : 'Other payment'} · ${booking.payment_status === 'paid' ? 'Paid' : booking.payment_status === 'refunded' ? 'Refunded' : 'Payment arranged with staff'}`;
        const note = document.createElement('p'); note.className = 'customer-booking-note';
        note.textContent = booking.status === 'pending' ? 'Your time is held. Staff approval is still required.' : booking.status === 'confirmed' ? 'Your booking is approved. We’ll see you at the fieldhouse.' : 'This booking was cancelled and its time released.';
        const participants = document.createElement('p'); participants.className = 'customer-booking-participants';
        participants.textContent = `${booking.party_size} ${booking.party_size === 1 ? 'participant' : 'participants'}`;
        card.append(top,times,participants,info,note);
        if (['pending','confirmed'].includes(booking.status) && new Date(booking.starts_at) > new Date()) {
          const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'customer-cancel-button'; cancel.textContent = 'Cancel booking';
          const feedback = document.createElement('p'); feedback.setAttribute('role','status');
          cancel.addEventListener('click', async () => {
            if (cancelling || !window.confirm(`Cancel ${booking.name} on ${date(booking.starts_at)} Eastern? This releases this date only. Any refund must be arranged with staff.`)) return;
            cancelling = true; generation++; cancel.disabled = true; feedback.textContent = 'Cancelling booking…';
            try {
              const response = await window.fieldhouseAuth.fetch(`/api/bookings/mine/${encodeURIComponent(booking.id)}/cancel`, {method:'POST'});
              if (response.status === 401) { sessionExpired(); return; }
              const result = await response.json();
              if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not cancel your booking. Please try again.');
              cancelling = false; offset = 0; await loadBookings();
              $('my-bookings-status').textContent = 'Booking cancelled and time released. View it in Past & cancelled. Contact staff about any refund.';
            } catch (error) { feedback.textContent = error.message; }
            finally { cancelling = false; cancel.disabled = false; }
          });
          const actions = document.createElement('div'); actions.className = 'customer-booking-actions';
          actions.append(cancel); card.append(actions,feedback);
        }
        return card;
      });
      $('my-bookings-list').replaceChildren(...cards);
      $('my-bookings-status').textContent = cards.length ? 'Status checked just now · Updates automatically while this page is open.' : view === 'upcoming' ? 'No upcoming bookings yet. Choose a time to get started.' : 'No past or cancelled bookings.';
      $('my-bookings-previous').hidden = offset === 0;
      $('my-bookings-next').hidden = !data.has_more;
    } catch (error) {
      if (current === generation) $('my-bookings-status').textContent = `${error.message} Use Refresh to try again; any displayed status may be out of date.`;
    } finally { if (current === generation) loading = false; }
  }
  function accountReady(user) {
    if (!user) { active = false; clearInterval(timer); $('account-summary').hidden = true; $('my-bookings-list').replaceChildren(); return; }
    const form = $('customer-profile-form');
    form.elements.name.value = user.name || '';
    form.elements.phone_number.value = user.phone_number || '';
    $('account-email-input').value = user.email;
    if (!active) {
      active = true; loadBookings(); clearInterval(timer);
      timer = setInterval(() => { if (document.visibilityState === 'visible') loadBookings(true); }, 20000);
    }
  }
  document.addEventListener('fieldhouse:account', event => accountReady(event.detail));
  window.fieldhouseAuth.ready.then(user => { if (user) accountReady(user); });
  document.querySelectorAll('[data-booking-view]').forEach(button => button.addEventListener('click', () => {
    view = button.dataset.bookingView; offset = 0;
    document.querySelectorAll('[data-booking-view]').forEach(b => b.setAttribute('aria-pressed',String(b === button)));
    $('my-bookings-list').replaceChildren(); loadBookings();
  }));
  $('my-bookings-refresh').addEventListener('click', () => loadBookings());
  $('my-bookings-next').addEventListener('click', () => { offset += 50; loadBookings(); });
  $('my-bookings-previous').addEventListener('click', () => { offset = Math.max(0, offset - 50); loadBookings(); });
  window.addEventListener('focus', () => loadBookings(true));
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') loadBookings(true); });
  $('customer-profile-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    $('customer-profile-status').textContent = 'Saving…';
    try {
      const response = await window.fieldhouseAuth.fetch('/api/auth/profile', {method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      if (response.status === 401) { sessionExpired(); return; }
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check your name and phone number.');
      $('customer-profile-status').textContent = 'Profile saved.';
      await window.fieldhouseAuth.reload();
    } catch (error) { $('customer-profile-status').textContent = error.message; }
    finally { button.disabled = false; }
  });
})();
