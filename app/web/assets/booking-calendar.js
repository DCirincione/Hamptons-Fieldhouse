(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('booking-calendar');
  const closeButton = $('close-booking-calendar');
  const service = $('booking-service');
  const form = $('reservation-form');
  const fields = form.elements;
  let customer = null;
  function updateCustomer(user) {
    customer = user;
    $('booking-account-notice').hidden = Boolean(user?.email_confirmed);
    if (user) {
      const names = (user.name || '').trim().split(/\s+/);
      if (!fields.first_name.value) fields.first_name.value = names.shift() || '';
      if (!fields.last_name.value) fields.last_name.value = names.join(' ');
      fields.email.value = user.email;
      if (!fields.phone_number.value) fields.phone_number.value = user.phone_number || '';
    }
    $('reserve-button').disabled = !user?.email_confirmed;
  }
  window.fieldhouseAuth.ready.then(updateCustomer);
  document.addEventListener('fieldhouse:account', event => updateCustomer(event.detail));
  const additionalDates = new Set();
  let additionalMonth, additionalSlots = [], additionalGeneration = 0, additionalLoading = false;
  const occurrenceCount = () => 1 + additionalDates.size;
  function setAdditionalExpanded(expanded) {
    $('additional-dates-panel').hidden = !expanded;
    $('toggle-additional-dates').setAttribute('aria-expanded', String(expanded));
    $('toggle-additional-dates').textContent = expanded ? 'Hide Calendar' : 'Book More Dates';
  }
  $('toggle-additional-dates').addEventListener('click', () => {
    const expanded = $('additional-dates-panel').hidden;
    setAdditionalExpanded(expanded);
    if (expanded) loadAdditional();
  });
  function resetAdditional() {
    setAdditionalExpanded(false);
    additionalDates.clear(); additionalSlots = []; additionalGeneration++;
  }
  function renderAdditional() {
    if (!selectedSlot) return;
    const first = new Date(`${additionalMonth}-01T12:00:00Z`);
    $('additional-month').textContent = first.toLocaleDateString('en-US', {month:'long', year:'numeric', timeZone:'UTC'});
    $('additional-time').textContent = `Same time on every date: ${time(selectedSlot.starts_at)}–${time(selectedSlot.ends_at)} Eastern.`;
    $('additional-previous').disabled = busy || additionalMonth <= selectedDate.slice(0,7);
    $('additional-next').disabled = busy || additionalMonth >= data.last_date.slice(0,7);
    const available = new Set(additionalSlots.filter(slot => time(slot.starts_at) === time(selectedSlot.starts_at)).map(slot => nyDate(slot.starts_at)));
    const grid = $('additional-days'); grid.replaceChildren();
    for (let i=0; i<first.getUTCDay(); i++) grid.append(document.createElement('span'));
    const days = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth()+1, 0)).getUTCDate();
    for (let day=1; day<=days; day++) {
      const key = `${additionalMonth}-${String(day).padStart(2,'0')}`;
      const original = key === selectedDate, chosen = original || additionalDates.has(key);
      const button = document.createElement('button'); button.type = 'button'; button.textContent = day;
      button.dataset.date = key;
      button.disabled = busy || original || additionalLoading || key < selectedDate || key > data.last_date || (!chosen && (!available.has(key) || additionalDates.size >= 29));
      button.setAttribute('aria-pressed', String(chosen));
      button.setAttribute('aria-label', `${dateLabel(key)} — ${original ? 'first booking date' : chosen ? 'selected, click to remove' : available.has(key) ? 'available at your selected time' : 'unavailable at your selected time'}`);
      button.addEventListener('click', () => { additionalDates.has(key) ? additionalDates.delete(key) : additionalDates.add(key); renderAdditional(); total(); });
      grid.append(button);
    }
    $('selected-dates').replaceChildren();
    [selectedDate, ...Array.from(additionalDates).sort()].forEach(key => {
      const chip = document.createElement(key === selectedDate ? 'span' : 'button');
      chip.textContent = new Date(`${key}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
      if (key !== selectedDate) {
        chip.type = 'button'; chip.disabled = busy; chip.textContent += ' ×';
        chip.setAttribute('aria-label', `Remove ${dateLabel(key)}`);
        chip.addEventListener('click', () => { additionalDates.delete(key); renderAdditional(); total(); });
      }
      $('selected-dates').append(chip);
    });
  }
  async function loadAdditional() {
    const current = ++additionalGeneration;
    additionalLoading = true; additionalSlots = []; renderAdditional();
    $('additional-status').textContent = 'Loading availability at your selected time…';
    $('additional-retry').hidden = true;
    try {
      const response = await fetch(`/api/bookings/availability?service=${encodeURIComponent(service.value)}&month=${additionalMonth}-01`, {cache:'no-store'});
      const result = await response.json();
      if (current !== additionalGeneration) return;
      if (!response.ok) throw new Error('Unable to load these dates. Please retry.');
      additionalSlots = result.slots;
      $('additional-status').textContent = 'Highlighted dates are selected. Click a date again to remove it.';
    } catch (error) {
      if (current !== additionalGeneration) return;
      $('additional-status').textContent = error.message || 'Unable to load these dates.';
      $('additional-retry').hidden = false;
    } finally {
      if (current === additionalGeneration) { additionalLoading = false; renderAdditional(); }
    }
  }
  for (const [id, offset] of [['additional-previous',-1],['additional-next',1]]) {
    $(id).addEventListener('click', () => {
      const date = new Date(`${additionalMonth}-01T12:00:00Z`); date.setUTCMonth(date.getUTCMonth()+offset);
      additionalMonth = date.toISOString().slice(0,7); loadAdditional();
    });
  }
  $('additional-retry').addEventListener('click', loadAdditional);
  const nyDate = value => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(value));
  const today = nyDate(new Date());
  const time = value => new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit'}).format(new Date(value));
  const dateLabel = value => new Intl.DateTimeFormat('en-US', {timeZone: 'UTC', weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'}).format(new Date(`${value}T12:00:00Z`));
  const money = cents => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(cents / 100);
  let month = today.slice(0, 7), data = null, selectedDate = null, selectedSlot = null;
  let generation = 0, busy = false, lastBody = null, requestId = null;
  const monthOffset = offset => {
    const d = new Date(`${month}-01T12:00:00Z`);
    d.setUTCMonth(d.getUTCMonth() + offset);
    return d.toISOString().slice(0, 7);
  };
  function resetSelection() {
    selectedDate = selectedSlot = null; resetAdditional();
    form.hidden = true;
    $('booking-slots').replaceChildren();
    $('slot-heading').textContent = 'Choose a date';
  }
  function renderCalendar() {
    const first = new Date(`${month}-01T12:00:00Z`);
    $('calendar-month').textContent = first.toLocaleDateString('en-US', {month: 'long', year: 'numeric', timeZone: 'UTC'});
    $('previous-month').disabled = busy || month <= (data?.today || today).slice(0, 7);
    const limit = data?.last_date?.slice(0, 7);
    $('next-month').disabled = busy || Boolean(limit && month >= limit);
    $('calendar-days').replaceChildren();
    for (let i = 0; i < first.getUTCDay(); i++) $('calendar-days').append(document.createElement('span'));
    const days = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
    for (let day = 1; day <= days; day++) {
      const key = `${month}-${String(day).padStart(2, '0')}`;
      const count = data?.slots.filter(slot => nyDate(slot.starts_at) === key).length || 0;
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = day;
      button.disabled = busy || !count;
      button.setAttribute('aria-label', `${dateLabel(key)} — ${count ? `${count} available times` : 'unavailable'}`);
      button.setAttribute('aria-pressed', String(selectedDate === key));
      button.addEventListener('click', () => { resetAdditional(); selectedDate = key; selectedSlot = null; form.hidden = true; renderCalendar(); renderSlots(); });
      $('calendar-days').append(button);
    }
  }
  function renderSlots() {
    $('booking-slots').replaceChildren();
    $('slot-heading').textContent = dateLabel(selectedDate);
    data.slots.filter(slot => nyDate(slot.starts_at) === selectedDate).forEach(slot => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${time(slot.starts_at)} – ${time(slot.ends_at)}`;
      button.setAttribute('aria-pressed', String(selectedSlot?.starts_at === slot.starts_at));
      button.disabled = busy;
      button.addEventListener('click', () => {
        resetAdditional(); selectedSlot = slot; additionalMonth = selectedDate.slice(0,7);
        $('reservation-status').textContent = '';
        $('booking-receipt').hidden = true;
        form.hidden = false;
        $('selected-booking').textContent = `${data.name} · ${dateLabel(selectedDate)} · ${time(slot.starts_at)}–${time(slot.ends_at)} Eastern`;
        renderSlots(); total(); renderAdditional();
      });
      $('booking-slots').append(button);
    });
  }
  async function load() {
    const current = ++generation;
    data = null; resetSelection(); renderCalendar();
    $('calendar-status').textContent = 'Loading available times…';
    $('reservation-status').textContent = '';
    try {
      const response = await fetch(`/api/bookings/availability?service=${encodeURIComponent(service.value)}&month=${month}-01`, {cache: 'no-store'});
      const result = await response.json();
      if (current !== generation) return;
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Availability could not be loaded. Please try again.');
      data = result;
      const party = data.category === 'birthday';
      $('party-options').hidden = !party;
      $('party-size-label').textContent = party ? 'Number of children' : 'Number of participants';
      fields.party_size.value = party ? data.included_children : 1;
      fields.own_food.checked = false;
      fields.extra_pizzas.value = 0;
      fields.extra_pizzas.disabled = !party || data.extra_pizza_cents === null;
      $('food-discount-label').textContent = `Bring your own food — save ${money(data.own_food_discount_cents)}`;
      $('calendar-status').textContent = data.slots.length ? 'Select an available date to see time blocks.' : 'No available times this month. Try another month or contact us.';
      renderCalendar();
    } catch (error) {
      if (current !== generation) return;
      $('calendar-status').textContent = error.message || 'Availability could not be loaded. Please try again.';
    }
  }
  function total() {
    if (!data) return 0;
    const rows = [`${data.name}: ${money(data.price_cents)}`];
    let amount = data.price_cents;
    if (data.category === 'birthday') {
      const kids = Math.max(0, Number(fields.party_size.value) - data.included_children);
      fields.extra_pizzas.disabled = data.extra_pizza_cents === null;
      if (fields.extra_pizzas.disabled) fields.extra_pizzas.value = 0;
      const pizzas = Number(fields.extra_pizzas.value);
      if (kids) { amount += kids * data.extra_child_cents; rows.push(`${kids} additional children: ${money(kids * data.extra_child_cents)}`); }
      if (pizzas) { amount += pizzas * data.extra_pizza_cents; rows.push(`${pizzas} additional pizzas: ${money(pizzas * data.extra_pizza_cents)}`); }
      if (fields.own_food.checked) { amount -= data.own_food_discount_cents; rows.push(`Bring-your-own-food discount: −${money(data.own_food_discount_cents)}`); }
    }
    $('booking-breakdown').replaceChildren(...rows.map(text => { const p = document.createElement('p'); p.textContent = text; return p; }));
    const count = occurrenceCount();
    $('booking-payment-plan').hidden = count === 1;
    $('pay-one-amount').textContent = `${money(amount)} now · ${money(amount * (count - 1))} for later sessions`;
    $('pay-all-amount').textContent = `${money(amount * count)} for all ${count} sessions`;
    const payAll = count > 1 && fields.payment_plan.value === 'all_sessions';
    $('booking-payment-summary').textContent = count > 1 ? `Payment to arrange now: ${money(amount * (payAll ? count : 1))}.${payAll ? '' : ' Remaining sessions are paid separately; arrange timing with staff.'}` : '';
    $('booking-total').textContent = count > 1 ? `${money(amount)} per date × ${count} dates · Total: ${money(amount * count)}` : `Total: ${money(amount)}`;
    $('booking-repeat-summary').textContent = `${count} date${count === 1 ? '' : 's'} · Each date is checked for availability and held pending staff approval.`;
    return amount;
  }
  function setBusy(value) {
    busy = value;
    $('reservation-fields').disabled = value;
    service.disabled = value;
    $('reserve-button').disabled = value || !customer?.email_confirmed;
    closeButton.disabled = value;
    $('refresh-calendar').disabled = value;
    document.querySelectorAll('[data-book-service]').forEach(a => a.setAttribute('aria-disabled', String(value)));
    renderCalendar(); if (selectedDate && data) renderSlots(); renderAdditional();
    $('reserve-button').textContent = value ? 'Holding your time…' : 'Request booking & hold time ↗';
  }
  form.addEventListener('input', total);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !customer?.email_confirmed || !selectedSlot || !data || !form.reportValidity()) return;
    if (occurrenceCount() < 1 || occurrenceCount() > 30) { $("reservation-status").textContent = "Choose between 1 and 30 dates."; return; }
    const body = Object.fromEntries(new FormData(form));
    body.service = service.value;
    body.starts_at = selectedSlot.starts_at;
    body.party_size = Number(body.party_size);
    body.extra_pizzas = Number(body.extra_pizzas || 0);
    body.own_food = fields.own_food.checked;
    body.expected_total_cents = total();
    body.payment_plan = occurrenceCount() > 1 ? fields.payment_plan.value : 'one_session';
    body.additional_dates = Array.from(additionalDates).sort();
    const fingerprint = JSON.stringify(body);
    if (!globalThis.crypto?.randomUUID) {
      $('reservation-status').textContent = 'Please open this website using HTTPS to submit a booking securely.';
      return;
    }
    if (fingerprint !== lastBody) { lastBody = fingerprint; requestId = crypto.randomUUID(); }
    body.request_id = requestId;
    setBusy(true);
    $('reservation-status').textContent = 'Submitting your booking request…';
    try {
      const response = await window.fieldhouseAuth.fetch('/api/bookings', {method: 'POST', body: JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 409) { await load(); }
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Please check your contact information and booking details.');
      }
      form.hidden = true;
      const receipt = $('booking-receipt');
      const bookings = result.bookings;
      const lines = [bookings.every(b => b.status === 'pending') ? 'Your time is held — awaiting staff approval' : 'Your booking request',
        `${data.name} · ${bookings.length} date${bookings.length === 1 ? '' : 's'}`,
        ...bookings.map(b => `${dateLabel(nyDate(b.starts_at))} · ${time(b.starts_at)}–${time(b.ends_at)} Eastern`),
        `Total: ${money(result.total_price_cents)} · Payment not collected online`,
        ...(bookings.length > 1 ? [`Selected payment: ${body.payment_plan === 'all_sessions' ? 'all sessions' : 'one session'} · ${money(body.payment_plan === 'all_sessions' ? result.total_price_cents : bookings[0].total_price_cents)} to arrange with staff now.${body.payment_plan === 'one_session' ? ' Remaining sessions are paid separately.' : ''}`] : []),
        `Request reference: ${result.request_id}`,
        'Track approval for each date in My Bookings. Contact 631-278-4374 to arrange payment.'];
      receipt.replaceChildren(...lines.map((text, i) => { const element = document.createElement(i ? 'p' : 'h3'); element.textContent = text; return element; }));
      const accountLink = document.createElement('a'); accountLink.href = '/account'; accountLink.className = 'button'; accountLink.textContent = 'View My Bookings →'; receipt.append(accountLink);
      receipt.hidden = false;
      await load();
      receipt.focus();
      lastBody = requestId = null;
    } catch (error) {
      $('reservation-status').textContent = `${error.message || 'Connection interrupted.'} If your connection was interrupted, retry without changing your details to avoid a duplicate request.`;
    } finally { setBusy(false); }
  });
  service.addEventListener('change', load);
  $('previous-month').addEventListener('click', () => { month = monthOffset(-1); load(); });
  $('next-month').addEventListener('click', () => { month = monthOffset(1); load(); });
  $('refresh-calendar').addEventListener('click', load);
  document.querySelectorAll('[data-book-service]').forEach(button => button.addEventListener('click', () => {
    if (busy) return;
    if (service.value !== button.dataset.bookService) $('booking-receipt').hidden = true;
    service.value = button.dataset.bookService;
    button.focus();
    dialog.showModal();
    document.body.classList.add('booking-modal-open');
    dialog.scrollTop = 0;
    load();
  }));
  document.querySelectorAll('[data-book-card]').forEach(card => card.addEventListener('click', event => {
    if (event.target.closest('button, a, input, select, textarea') || window.getSelection()?.toString()) return;
    card.querySelector('[data-book-service]').click();
  }));
  closeButton.addEventListener('click', () => { if (!busy) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('click', event => {
    const box = dialog.getBoundingClientRect();
    if (!busy && event.target === dialog && (event.clientX < box.left || event.clientX > box.right ||
        event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
  });
  dialog.addEventListener('close', () => document.body.classList.remove('booking-modal-open'));
})();
