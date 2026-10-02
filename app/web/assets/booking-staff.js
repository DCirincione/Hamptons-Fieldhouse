(() => {
  const $ = id => document.getElementById(id);
  let generation = 0, activeSection = 'reservations';
  function showSection(section) {
    activeSection = section;
    $('staff-schedule').hidden = section !== 'availability';
    $('staff-reservations').hidden = section !== 'reservations';
    $('availability-tab').setAttribute('aria-pressed', String(section === 'availability'));
    $('reservations-tab').setAttribute('aria-pressed', String(section === 'reservations'));
  }
  $('availability-tab').addEventListener('click', () => showSection('availability'));
  $('reservations-tab').addEventListener('click', () => showSection('reservations'));
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
    const current = ++generation;
    $('staff-status').textContent = 'Loading bookings…';
    $('staff-bookings').replaceChildren();
    try {
      const bookings = await call('');
      if (current !== generation) return;
      $('staff-controls').hidden = false;
      showSection(activeSection);
      loadSchedule();
      bookings.sort((a, b) => Number(b.status === 'pending') - Number(a.status === 'pending'));
      bookings.forEach(booking => {
        const card = document.createElement('article'); card.className = 'card staff-booking';
        const heading = document.createElement('h2'); heading.textContent = `${booking.status === 'pending' ? 'Pending approval' : 'Approved'} · ${booking.offerings?.name || 'Booking'}`;
        const details = document.createElement('p');
        const extras = (booking.booking_line_items || []).map(item => `${item.quantity} × ${item.booking_extras?.name || 'Extra'}`).join(', ');
        details.textContent = `${date(booking.starts_at)} – ${date(booking.ends_at)} Eastern\n${booking.first_name} ${booking.last_name} · ${booking.party_size} participants\n${booking.email} · ${booking.phone_number}\n${money(booking.total_price_cents)} · ${booking.payment_method} · ${booking.payment_status}\n${booking.own_food ? 'Bringing own food' : 'Standard package'}${extras ? ` · ${extras}` : ''}\nReference: ${booking.id}${booking.notes ? `\nNotes: ${booking.notes}` : ''}`;
        const actions = document.createElement('div'); actions.className = 'staff-actions';
        (booking.status === 'pending' ? ['approve', 'cancel'] : ['cancel']).forEach(action => {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'button';
          button.textContent = action === 'approve' ? 'Approve booking' : 'Cancel & release time';
          button.addEventListener('click', async () => {
            if (!window.confirm(action === 'approve' ? 'Approve this booking after checking payment arrangements?' : 'Cancel this booking and release its time?')) return;
            actions.querySelectorAll('button').forEach(b => b.disabled = true);
            try { await call(`/${booking.id}`, {method: 'POST', body: JSON.stringify({action})}); await load(); }
            catch (error) { $('staff-status').textContent = error.message; actions.querySelectorAll('button').forEach(b => b.disabled = false); }
          }); actions.append(button);
        });
        card.append(heading, details, actions); $('staff-bookings').append(card);
      });
      $('staff-status').textContent = bookings.length ? `${bookings.filter(b => b.status === 'pending').length} pending · ${bookings.length} active ${bookings.length === 1 ? 'booking' : 'bookings'}` : 'No active bookings.';
    } catch (error) { if (current === generation) $('staff-status').textContent = error.message; }
  }
  $('staff-refresh').addEventListener('click', load);
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
      if (type === 'time') { input.min = index === 1 ? '06:00' : '06:01'; input.max = index === 1 ? '22:59' : '23:00'; }
      else input.min = today;
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
    scheduleRows = null;
    $('schedule-day').replaceChildren(); $('schedule-entries').replaceChildren();
    if (!day) { $('schedule-status').textContent = 'Choose a date.'; return; }
    $('schedule-status').textContent = 'Loading schedule…';
    try {
      const rows = await call(`/schedule?month=${day.slice(0, 7)}-01`);
      if (current !== scheduleGeneration) return;
      scheduleRows = rows; renderDay();
      $('schedule-status').textContent = 'Click an open hour to fill in a block, or enter custom times below. Crossed-out hours contain reserved time.';
    } catch (error) { if (current === scheduleGeneration) $('schedule-status').textContent = error.message; }
  }
  function renderDay() {
    if (!scheduleRows) return;
    const day = $('schedule-date').value, resource = $('schedule-resource').value;
    const rows = scheduleRows.filter(row => localDate(row.starts_at) === day && row.resource === resource);
    $('schedule-day').replaceChildren(); $('schedule-entries').replaceChildren();
    for (let hour = 6; hour < 23; hour++) {
      const collisions = rows.filter(row => minutes(row.starts_at) < (hour + 1) * 60 && minutes(row.ends_at) > hour * 60);
      const button = document.createElement('button'); button.type = 'button';
      const start = `${String(hour).padStart(2, '0')}:00`, end = `${String(hour+1).padStart(2, '0')}:00`;
      button.textContent = `${start}–${end} · ${collisions.length ? 'Reserved' : 'Open'}`;
      button.disabled = Boolean(collisions.length) || blockBusy || day < today;
      if (collisions.length) { button.className = 'schedule-reserved'; button.title = collisions.map(row => row.title).join(', '); }
      button.addEventListener('click', () => {
        $('block-mode').value = 'dates'; $('block-dates').replaceChildren(); addDate(day, start, end); setMode();
        document.querySelectorAll('[name=resource]').forEach(input => input.checked = input.value === resource);
        $('block-form').scrollIntoView({behavior: 'smooth', block: 'start'}); $('block-form').elements.title.focus({preventScroll:true});
      });
      $('schedule-day').append(button);
    }
    rows.forEach(row => {
      const entry = document.createElement('div'); entry.className = 'schedule-entry';
      const details = document.createElement('p'); details.textContent = `${clock(row.starts_at)}–${clock(row.ends_at)} · ${row.title} · ${row.status}`;
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
      } else { const note = document.createElement('p'); note.textContent = 'Manage this reservation in the booking queue below.'; entry.append(note); }
      $('schedule-entries').append(entry);
    });
    if (!rows.length) $('schedule-entries').textContent = `No reserved times for ${scheduleNames[resource]} on this date.`;
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
      await loadSchedule();
    } catch (error) { $('block-status').textContent = error.message; }
    finally { blockBusy = false; $('block-fields').disabled = false; $('staff-logout').disabled = false; renderDay(); }
  });
  $('schedule-date').addEventListener('change', loadSchedule);
  $('schedule-resource').addEventListener('change', renderDay);
  $('schedule-refresh').addEventListener('click', loadSchedule);
  $('block-add-date').addEventListener('click', () => addDate());
  $('block-mode').addEventListener('change', setMode);
  $('block-form').addEventListener('input', preview);
  addDate(); setMode();
  load();
})();
