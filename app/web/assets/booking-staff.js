(() => {
  const $ = id => document.getElementById(id);
  let generation = 0, activeSection = 'availability', bookings = null, bookingsGeneration = 0, hoursGeneration = 0;
  let dateHoursDirty = false, dateHoursDay = null;
  function showSection(section) {
    activeSection = section;
    $('staff-schedule').hidden = section !== 'availability';
    $('staff-offerings').hidden = section !== 'offerings';
    $('staff-contacts').hidden = section !== 'contacts';
    $('staff-gallery').hidden = section !== 'gallery';
    $('availability-tab').setAttribute('aria-pressed', String(section === 'availability'));
    $('offerings-tab').setAttribute('aria-pressed', String(section === 'offerings'));
    $('contacts-tab').setAttribute('aria-pressed', String(section === 'contacts'));
    $('gallery-tab').setAttribute('aria-pressed', String(section === 'gallery'));
  }
  $('availability-tab').addEventListener('click', () => showSection('availability'));
  $('offerings-tab').addEventListener('click', () => { showSection('offerings'); window.dispatchEvent(new Event('fieldhouse:offerings-open')); });
  $('contacts-tab').addEventListener('click', () => { showSection('contacts'); window.dispatchEvent(new Event('fieldhouse:contacts-open')); });
  $('gallery-tab').addEventListener('click', () => { showSection('gallery'); window.dispatchEvent(new Event('fieldhouse:gallery-open')); });
  const money = n => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(n / 100);
  const date = value => new Date(value).toLocaleString('en-US', {timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short'});
  async function call(path, options = {}) {
    const response = await window.fieldhouseAuth.fetch(`/api/bookings/staff${path}`, options);
    if (response.status === 401) { location.replace('/account?next=admin'); throw new Error('Please sign in again.'); }
    if (response.status === 403) { location.replace('/account'); throw new Error('Admin permission is required.'); }
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not process this request.');
    return data;
  }
  async function load() {
    ++generation;
    $('staff-controls').hidden = false;
    showSection(activeSection);
    await Promise.allSettled([loadBookings(), loadSchedule(), loadHours()]);
  }
  async function loadBookings() {
    const current = ++bookingsGeneration;
    const month = ($('schedule-date').value || today).slice(0, 7);
    bookings = null;
    $('staff-status').textContent = 'Loading bookings…';
    $('calendar-booking-status').textContent = 'Loading booking indicators…';
    renderBookings(); renderMonth();
    try {
      const result = await call(`?month=${month}-01`);
      if (current !== bookingsGeneration) return;
      bookings = result;
      $('staff-status').textContent = bookings.length ? `${bookings.filter(b => b.status === 'pending').length} awaiting confirmation · ${bookings.filter(b => b.status === 'confirmed').length} confirmed this month` : 'No active bookings this month.';
      $('calendar-booking-status').textContent = '';
      renderBookings(); renderMonth();
    } catch (error) {
      if (current !== bookingsGeneration) return;
      $('staff-status').textContent = error.message;
      $('calendar-booking-status').textContent = 'Booking indicators could not be loaded. Refresh to retry.';
      $('day-bookings-status').textContent = 'Bookings could not be loaded. Use Refresh to retry.';
    }
  }
  function renderBookings() {
    $('staff-bookings').replaceChildren();
    if (!bookings) { $('day-bookings-status').textContent = 'Loading bookings…'; return; }
      const selectedBookings = bookings.filter(booking => localDate(booking.starts_at) === $('schedule-date').value);
      selectedBookings.sort((a, b) => Number(b.status === 'pending') - Number(a.status === 'pending'));
      selectedBookings.forEach(booking => {
        const card = document.createElement('details'); card.className = 'card staff-booking'; card.dataset.bookingId = booking.id;
        const heading = document.createElement('summary');
        const state = document.createElement('span'); state.className = booking.status === 'pending' ? 'booking-state pending' : 'booking-state confirmed';
        state.textContent = booking.status === 'pending' ? 'Awaiting confirmation' : 'Confirmed';
        const title = document.createElement('strong'); title.textContent = `${clock(booking.starts_at)}–${clock(booking.ends_at)} · ${booking.offerings?.name || 'Booking'}`;
        heading.append(state, title);
        const details = document.createElement('p');
        const extras = (booking.booking_line_items || []).map(item => `${item.quantity} × ${item.booking_extras?.name || 'Extra'}`).join(', ');
        const repeating = booking.customer_request_id && bookings.filter(b => b.customer_request_id === booking.customer_request_id).length > 1;
        const paymentChoice = booking.session_count > 1 && booking.payment_plan
          ? `\nPayment choice: ${booking.payment_plan === 'all_sessions' ? 'All sessions now' : 'One session now'} · ${money(booking.initial_payment_cents)} requested now for the ${booking.session_count}-session request (not per date). Payment not verified by this choice.` : '';
        details.textContent = `${repeating ? 'Repeating schedule · approve each date separately\n' : ''}${date(booking.starts_at)} – ${date(booking.ends_at)} Eastern\n${booking.first_name} ${booking.last_name} · ${booking.party_size} participants\n${booking.email} · ${booking.phone_number}\n${money(booking.total_price_cents)} · ${booking.payment_method} · ${booking.payment_status}${paymentChoice}\n${booking.own_food ? 'Bringing own food' : 'Standard package'}${extras ? ` · ${extras}` : ''}\nReference: ${booking.id}${booking.notes ? `\nNotes: ${booking.notes}` : ''}`;
        const actions = document.createElement('div'); actions.className = 'staff-actions';
        const availableActions = booking.status === 'pending' ? ['approve'] : [];
        if (booking.payment_status === 'unpaid' && ['venmo','cash','other'].includes(booking.payment_method)) {
          availableActions.push(booking.status === 'pending' ? 'approve_paid' : 'mark_paid');
        }
        availableActions.push('cancel');
        const labels = {approve:'Confirm booking', approve_paid:'Confirm & mark paid', mark_paid:'Mark as paid', cancel:'Cancel & release time'};
        availableActions.forEach(action => {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'button';
          button.textContent = labels[action];
          button.addEventListener('click', async () => {
            const prompt = action === 'approve_paid' || action === 'mark_paid'
              ? `${action === 'approve_paid' ? 'Confirm this booking and record' : 'Record'} ${money(booking.total_price_cents)} as paid via ${booking.payment_method}? Only continue if you have received the full payment for this date. This does not charge the customer.`
              : action === 'approve' ? 'Confirm this booking after checking payment arrangements? Payment status will stay unchanged.' : 'Cancel this booking and release its time?';
            if (!window.confirm(prompt)) return;
            actions.querySelectorAll('button').forEach(b => b.disabled = true);
            try { await call(`/${booking.id}`, {method: 'POST', body: JSON.stringify({action})}); await load(); }
            catch (error) { $('staff-status').textContent = error.message; actions.querySelectorAll('button').forEach(b => b.disabled = false); }
          }); actions.append(button);
        });
        card.append(heading, details, actions); $('staff-bookings').append(card);
      });
      const hasBlocks = (scheduleRows || []).some(row => !row.booking_id && localDate(row.starts_at) === $('schedule-date').value && ($('schedule-resource').value === 'all' || row.resource === $('schedule-resource').value));
      $('day-bookings-status').textContent = selectedBookings.length || hasBlocks ? 'Select a booked time to view details.' : 'No bookings on this date.';
  }
  $('staff-refresh').addEventListener('click', () => {
    load();
    if (activeSection === 'contacts') window.dispatchEvent(new Event('fieldhouse:contacts-open'));
    if (activeSection === 'offerings') window.dispatchEvent(new Event('fieldhouse:offerings-refresh'));
  });
  $('staff-logout').addEventListener('click', async () => {
    $('staff-logout').disabled = true;
    try { await window.fieldhouseAuth.signOut(); }
    catch (error) { $('staff-status').textContent = error.message; $('staff-logout').disabled = false; }
  });

  const scheduleNames = {field: 'Full field', backspace: 'Speed & agility + batting cage', 'party-area': 'Party area'};
  const localDate = value => new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(value));
  const clock = value => new Date(value).toLocaleTimeString('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit'});
  const today = localDate(new Date());
  $('schedule-date').value = today;
  $('block-first').value = $('block-last').value = today;
  let hours = null, hoursDirty = false, hoursBusy = false;
  const endDate = new Date(`${today}T12:00:00Z`); endDate.setUTCDate(endDate.getUTCDate() + 365);
  const lastDay = endDate.toISOString().slice(0, 10);
  let scheduleRows = null, scheduleGeneration = 0, blockBusy = false, lastBlockBody = null, blockRequestId = null;
  function minutes(value) {
    const parts = new Intl.DateTimeFormat('en-GB', {timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date(value)).split(':');
    return Number(parts[0]) * 60 + Number(parts[1]);
  }
  function label(text, input) { const el = document.createElement('label'); el.append(text, input); return el; }
  function addDate(day = $('schedule-date').value || today, start = '18:00', end = '19:00') {
    const row = document.createElement('div'); row.className = 'block-date-row';
    [['date', day, 'Date'], ['time', start, 'Start time'], ['time', end, 'End time']].forEach(([type, value, title], index) => {
      const input = document.createElement('input'); input.type = type; input.value = value; input.required = true;
      input.dataset.part = ['date', 'start', 'end'][index];
      if (type === 'date') { input.min = today; input.max = lastDay; }
      row.append(label(title, input));
    });
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove date';
    remove.addEventListener('click', () => { row.remove(); preview(); }); row.append(remove);
    $('block-dates').append(row); preview();
  }
  function setMode() {
    const repeat = $('block-mode').value !== 'dates';
    $('block-individual').hidden = repeat; $('block-repeat').hidden = !repeat;
    $('block-weekdays').hidden = $('block-mode').value !== 'weekly';
    $('block-individual').querySelectorAll('input').forEach(input => input.disabled = repeat);
    ['block-first', 'block-last', 'block-start', 'block-end'].forEach(id => { $(id).disabled = !repeat; $(id).required = repeat; });
    preview();
  }
  function preview() {
    const mode = $('block-mode').value;
    let count = 0;
    if (mode === 'dates') count = $('block-dates').children.length;
    else if ($('block-first').value && $('block-last').value) {
      const first = new Date(`${$('block-first').value}T12:00:00Z`), last = new Date(`${$('block-last').value}T12:00:00Z`);
      const days = [...document.querySelectorAll('[name=weekday]:checked')].map(input => Number(input.value));
      for (let i = 0, d = first; d <= last && i < 367; i++, d.setUTCDate(d.getUTCDate() + 1)) {
        if (mode === 'daily' || days.includes((d.getUTCDay() + 6) % 7)) count++;
      }
    }
    $('block-preview').textContent = `${count} date${count === 1 ? '' : 's'} selected. Repeating schedules require an end date within the next year.`;
  }
  async function loadSchedule() {
    const current = ++scheduleGeneration;
    const day = $('schedule-date').value;
    scheduleRows = null; renderMonth();
    $('block-custom').disabled = true;
    $('schedule-entries').replaceChildren();
    if (!day) { $('schedule-status').textContent = 'Choose a date.'; return; }
    $('schedule-status').textContent = 'Loading schedule…';
    try {
      const rows = await call(`/schedule?month=${day.slice(0, 7)}-01`);
      if (current !== scheduleGeneration) return;
      scheduleRows = rows;
      renderMonth(); renderDay();
      $('schedule-status').textContent = '';
    } catch (error) { if (current === scheduleGeneration) { $('schedule-status').textContent = error.message; renderDay(); } }
  }
  function renderDay() {
    const day = $('schedule-date').value, resource = $('schedule-resource').value;
    if (!day) return;
    renderBookings();
    const rows = (scheduleRows || []).filter(row => localDate(row.starts_at) === day && (resource === 'all' || row.resource === resource));
    $('schedule-entries').replaceChildren();
    const opening = hours ? effectiveHours(day) : null;
    $('schedule-day-title').textContent = dayLabel(day);
    $('schedule-hours-summary').textContent = !opening ? 'Opening hours are unavailable. Retry loading hours below.' : opening.opens ? `Open ${formatTime(opening.opens)}–${formatTime(opening.closes)}${opening.override ? ' · Custom hours' : ''}` : 'Closed all day';
    $('date-hours-fields').disabled = !hours || hoursBusy || day < today || day > lastDay;
    $('block-custom').disabled = !scheduleRows || blockBusy || day < today || day > lastDay;
    if (opening && (dateHoursDay !== day || !dateHoursDirty)) {
      $('date-hours-closed').checked = !opening.opens;
      $('date-hours-opens').value = opening.opens?.slice(0, 5) || '06:00';
      $('date-hours-closes').value = opening.closes?.slice(0, 5) || '23:00';
      dateHoursDirty = false; dateHoursDay = day;
      toggleDateClosed();
    }
    rows.filter(row => !row.booking_id).forEach(row => {
      const entry = document.createElement('details'); entry.className = 'schedule-entry booked-entry';
      const summary = document.createElement('summary');
      const state = document.createElement('span'); state.className = 'booking-state confirmed'; state.textContent = 'Booked';
      const title = document.createElement('strong'); title.textContent = `${clock(row.starts_at)}–${clock(row.ends_at)} · ${scheduleNames[row.resource]}`;
      summary.append(state, title); entry.append(summary);
      const details = document.createElement('p'); details.textContent = `Manually blocked · ${row.title}`;
      entry.append(details);
      if (!row.booking_id) {
        const actions = document.createElement('div'); actions.className = 'staff-actions';
        (row.series_id ? ['occurrence', 'series'] : ['occurrence']).forEach(scope => {
          const button = document.createElement('button'); button.type = 'button'; button.textContent = scope === 'series' ? 'Remove entire series' : 'Release this time';
          button.addEventListener('click', async () => {
            if (!confirm(scope === 'series' ? 'Remove every block in this series, on all dates and selected spaces?' : 'Release this occurrence on all its selected spaces?')) return;
            button.disabled = true;
            const session = generation;
            try { await call('/schedule/remove', {method:'POST', body:JSON.stringify({slot_id:row.id, scope})}); if (session === generation) await loadSchedule(); }
            catch (error) { if (session === generation) { $('schedule-status').textContent = error.message; button.disabled = false; } }
          }); actions.append(button);
        }); entry.append(actions);
      }
      $('schedule-entries').append(entry);
    });
    if (!scheduleRows) $('schedule-entries').textContent = 'Booked times could not be loaded. Refresh to retry.';
  }
  $('block-form').addEventListener('submit', async event => {
    event.preventDefault(); if (blockBusy) return;
    const form = $('block-form');
    const body = {title: form.elements.title.value, resources: [...form.querySelectorAll('[name=resource]:checked')].map(el => el.value), mode: $('block-mode').value};
    if (!body.resources.length) { $('block-status').textContent = 'Select at least one space.'; return; }
    if (body.mode === 'dates') body.dates = [...$('block-dates').children].map(row => Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.dataset.part,input.value])));
    else {
      Object.assign(body, {start_date:$('block-first').value,end_date:$('block-last').value,start:$('block-start').value,end:$('block-end').value});
      if (body.mode === 'weekly') body.weekdays = [...form.querySelectorAll('[name=weekday]:checked')].map(el => Number(el.value));
    }
    const fingerprint = JSON.stringify(body);
    if (!crypto.randomUUID) { $('block-status').textContent = 'Use HTTPS to save scheduling changes.'; return; }
    if (fingerprint !== lastBlockBody) { lastBlockBody = fingerprint; blockRequestId = crypto.randomUUID(); }
    body.request_id = blockRequestId;
    blockBusy = true; $('block-fields').disabled = true; $('staff-logout').disabled = true;
    $('block-status').textContent = 'Saving blocked times…';
    try {
      const result = await call('/schedule', {method:'POST',body:JSON.stringify(body)});
      $('block-status').textContent = `Saved ${result.occurrences} date${result.occurrences === 1 ? '' : 's'}. These times are now unavailable for online booking.`;
      // Retain the request ID for an unchanged resubmission, including after success.
      $('schedule-date').value = body.mode === 'dates' ? body.dates[0].date : body.start_date;
      await Promise.allSettled([loadSchedule(), loadBookings()]);
    } catch (error) { $('block-status').textContent = error.message; }
    finally { blockBusy = false; $('block-fields').disabled = false; $('staff-logout').disabled = false; renderDay(); }
  });

  const formatTime = value => { const h = Number(value.slice(0, 2)); return `${h % 12 || 12}:${value.slice(3, 5)} ${h >= 12 ? 'PM' : 'AM'}`; };
  const dayLabel = value => new Date(`${value}T12:00:00Z`).toLocaleDateString('en-US', {timeZone:'UTC', weekday:'long', month:'long', day:'numeric', year:'numeric'});
  function effectiveHours(day) {
    const override = hours.overrides.find(row => row.date === day);
    const weekday = (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
    return override ? {...override, override:true} : hours.days.find(row => row.weekday === weekday);
  }
  function renderMonth() {
    const day = $('schedule-date').value || today, month = day.slice(0, 7);
    const first = new Date(`${month}-01T12:00:00Z`);
    $('schedule-month').textContent = first.toLocaleDateString('en-US', {timeZone:'UTC', month:'long', year:'numeric'});
    $('schedule-calendar').replaceChildren();
    for (let i = 0; i < first.getUTCDay(); i++) $('schedule-calendar').append(document.createElement('span'));
    const total = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
    for (let n = 1; n <= total; n++) {
      const key = `${month}-${String(n).padStart(2, '0')}`;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = n;
      const manualCount = new Set((scheduleRows || []).filter(row => !row.booking_id && localDate(row.starts_at) === key).map(row => row.series_id ? `${row.series_id}:${row.starts_at}:${row.ends_at}` : row.id)).size;
      const appointments = (bookings || []).filter(booking => localDate(booking.starts_at) === key);
      const pending = appointments.filter(booking => booking.status === 'pending').length;
      const confirmed = appointments.filter(booking => booking.status === 'confirmed').length + manualCount;
      const badges = document.createElement('span'); badges.className = 'calendar-booking-badges';
      if (pending) {
        const badge = document.createElement('span'); badge.className = 'calendar-pending'; badge.textContent = '!';
        badge.title = `${pending} awaiting confirmation`; badge.setAttribute('aria-hidden', 'true'); badges.append(badge);
      }
      if (confirmed) {
        const badge = document.createElement('span'); badge.className = 'calendar-confirmed'; badge.textContent = '✓';
        badge.title = `${confirmed} booked appointment${confirmed === 1 ? '' : 's'}`; badge.setAttribute('aria-hidden', 'true'); badges.append(badge);
      }
      button.append(badges);
      const closed = hours && !effectiveHours(key).opens;
      button.setAttribute('aria-label', `${dayLabel(key)}${closed ? ', closed' : ''}${pending ? `, ${pending} awaiting confirmation` : ''}${confirmed ? `, ${confirmed} booked appointments` : ''}`);
      button.setAttribute('aria-pressed', String(key === day));
      if (key === today) button.setAttribute('aria-current', 'date');
      button.classList.toggle('is-closed', Boolean(closed));
      button.addEventListener('click', () => {
        $('schedule-date').value = key;
        $('date-hours-status').textContent = '';
        renderMonth(); renderDay();
      });
      $('schedule-calendar').append(button);
    }
  }
  function moveMonth(delta) {
    const current = new Date(`${$('schedule-date').value.slice(0, 7)}-01T12:00:00Z`);
    current.setUTCMonth(current.getUTCMonth() + delta);
    $('schedule-date').value = current.toISOString().slice(0, 10);
    $('date-hours-status').textContent = '';
    loadSchedule(); loadBookings();
  }
  $('schedule-previous').addEventListener('click', () => moveMonth(-1));
  $('schedule-next').addEventListener('click', () => moveMonth(1));
  function openBlock(day, start = '18:00', end = '19:00') {
    if (blockBusy) return;
    $('block-mode').value = 'dates'; $('block-dates').replaceChildren(); addDate(day, start, end); setMode();
    $('block-first').value = $('block-last').value = day;
    $('block-start').value = start; $('block-end').value = end;
    document.querySelectorAll('[name=resource]').forEach(input => input.checked = input.value === ($('schedule-resource').value === 'all' ? 'field' : $('schedule-resource').value));
    $('block-status').textContent = '';
    $('block-dialog').showModal();
    $('block-form').elements.title.focus();
  }
  $('block-custom').addEventListener('click', () => openBlock($('schedule-date').value));
  $('block-close').addEventListener('click', () => { if (!blockBusy) $('block-dialog').close(); });
  $('block-dialog').addEventListener('cancel', event => { if (blockBusy) event.preventDefault(); });
  const hourRows = [...document.querySelectorAll('[data-weekday]')];
  async function loadHours() {
    const current = ++hoursGeneration;
    $('hours-retry').hidden = true;
    if (!hours) $('hours-status').textContent = 'Loading opening hours…';
    try {
      const loaded = await call('/schedule/hours');
      if (current !== hoursGeneration) return;
      if (!Array.isArray(loaded.days) || loaded.days.length !== 7 || !Array.isArray(loaded.overrides)) throw new Error('Opening hours could not be read. Retry loading hours.');
      hours = loaded;
      if (!hoursDirty) fillWeeklyHours();
      $('hours-status').textContent = hoursDirty ? 'Unsaved weekly hours. Save to update availability.' : '';
      renderMonth(); renderDay();
    } catch (error) {
      if (current !== hoursGeneration) return;
      $('hours-status').textContent = error.message;
      $('hours-retry').hidden = false;
      $('weekly-hours-fields').disabled = !hours || hoursBusy;
      renderDay();
    }
  }
  $('hours-retry').addEventListener('click', loadHours);
  function summarizeHours(row) {
    const closed = row.querySelector('[data-hours-closed]').checked;
    const opens = row.querySelector('[data-hours-opens]').value;
    const closes = row.querySelector('[data-hours-closes]').value;
    row.querySelector('[data-hours-summary]').textContent = closed ? 'Closed' : opens && closes ? `${formatTime(opens)}–${formatTime(closes)}` : 'Choose hours';
  }

  function toggleClosed(row) {
    const closed = row.querySelector('[data-hours-closed]').checked;
    row.querySelectorAll('input[type=time]').forEach(input => input.disabled = closed);
    summarizeHours(row);
  }
  function fillWeeklyHours() {
    hourRows.forEach(row => {
      const saved = hours.days.find(day => day.weekday === Number(row.dataset.weekday));
      row.querySelector('[data-hours-closed]').checked = !saved.opens;
      row.querySelector('[data-hours-opens]').value = saved.opens?.slice(0, 5) || '06:00';
      row.querySelector('[data-hours-closes]').value = saved.closes?.slice(0, 5) || '23:00';
      toggleClosed(row);
    });
    const common = [...hours.days].sort((a, b) => hours.days.filter(day => day.opens === b.opens && day.closes === b.closes).length - hours.days.filter(day => day.opens === a.opens && day.closes === a.closes).length)[0];
    $('hours-all-closed').checked = !common.opens;
    $('hours-all-opens').value = common.opens?.slice(0, 5) || '06:00';
    $('hours-all-closes').value = common.closes?.slice(0, 5) || '23:00';
    toggleAllClosed();
    $('weekly-hours-fields').disabled = hoursBusy;
  }
  function toggleAllClosed() { $('hours-all-opens').disabled = $('hours-all-closes').disabled = $('hours-all-closed').checked; }
  $('hours-all-closed').addEventListener('change', toggleAllClosed);
  $('weekly-hours-form').addEventListener('input', event => {
    hoursDirty = true;
    const row = event.target.closest('[data-weekday]'); if (row) toggleClosed(row);
  });
  $('hours-apply-all').addEventListener('click', () => {
    hourRows.forEach(row => {
      row.querySelector('[data-hours-closed]').checked = $('hours-all-closed').checked;
      row.querySelector('[data-hours-opens]').value = $('hours-all-opens').value;
      row.querySelector('[data-hours-closes]').value = $('hours-all-closes').value;
      toggleClosed(row);
    });
    hoursDirty = true;
    $('hours-status').textContent = 'Applied to all weekdays. Save weekly hours to update availability.';
  });
  function readHours(closed, opens, closes) {
    if (closed) return {opens:null, closes:null};
    if (!opens || !closes || opens >= closes) throw new Error('Closing time must be after opening time on the same day.');
    return {opens, closes};
  }
  $('weekly-hours-form').addEventListener('submit', async event => {
    event.preventDefault(); if (hoursBusy) return;
    try {
      const days = hourRows.map(row => {
        try { return {weekday:Number(row.dataset.weekday), ...readHours(row.querySelector('[data-hours-closed]').checked, row.querySelector('[data-hours-opens]').value, row.querySelector('[data-hours-closes]').value)}; }
        catch (error) { row.open = true; throw new Error(`${row.dataset.dayName}: ${error.message}`); }
      });
      hoursBusy = true; $('weekly-hours-fields').disabled = true;
      $('hours-status').textContent = 'Saving weekly hours…';
      const saved = await call('/schedule/hours', {method:'PUT',body:JSON.stringify({days})});
      hours = saved; hoursDirty = false; fillWeeklyHours(); renderMonth(); renderDay();
      $('hours-status').textContent = 'Weekly hours saved. Existing bookings are unchanged.';
    } catch (error) { $('hours-status').textContent = error.message; }
    finally { hoursBusy = false; $('weekly-hours-fields').disabled = false; if (hours) renderDay(); }
  });
  function toggleDateClosed() {
    $('date-hours-opens').disabled = $('date-hours-closes').disabled = $('date-hours-closed').checked;
  }
  $('date-hours-closed').addEventListener('change', toggleDateClosed);
  $('date-hours-form').addEventListener('input', () => { dateHoursDirty = true; });
  async function saveDateHours(reset) {
    if (hoursBusy) return;
    const day = $('schedule-date').value;
    try {
      const interval = reset ? {opens:null,closes:null} : readHours($('date-hours-closed').checked, $('date-hours-opens').value, $('date-hours-closes').value);
      hoursBusy = true; $('date-hours-fields').disabled = true;
      $('date-hours-status').textContent = 'Saving date hours…';
      const saved = await call('/schedule/hours/date', {method:'PUT',body:JSON.stringify({date:day,reset,...interval})});
      hours = saved; dateHoursDirty = false; renderMonth(); renderDay();
      $('date-hours-status').textContent = `${dayLabel(day)}: ${reset ? 'weekly hours restored' : 'hours saved'}. Existing bookings are unchanged.`;
    } catch (error) { $('date-hours-status').textContent = error.message; }
    finally { hoursBusy = false; $('date-hours-fields').disabled = !hours || $('schedule-date').value < today || $('schedule-date').value > lastDay; }
  }
  $('date-hours-form').addEventListener('submit', event => { event.preventDefault(); saveDateHours(false); });
  $('date-hours-reset').addEventListener('click', () => saveDateHours(true));

  $('schedule-date').addEventListener('change', () => { dateHoursDirty = false; $('date-hours-status').textContent = ''; loadSchedule(); loadBookings(); });
  $('schedule-resource').addEventListener('change', () => { renderMonth(); renderDay(); });
  $('schedule-refresh').addEventListener('click', load);
  $('block-add-date').addEventListener('click', () => addDate());
  $('block-mode').addEventListener('change', setMode);
  $('block-form').addEventListener('input', preview);
  addDate(); setMode();
  renderMonth();
  load();
})();
