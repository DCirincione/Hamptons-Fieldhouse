(() => {
  const dataNode = document.getElementById('camp-program-data');
  const dialog = document.getElementById('camp-registration-dialog');
  const infoDialog = document.getElementById('camp-info-dialog');
  const infoContent = document.getElementById('camp-info-content');
  const form = document.getElementById('camp-registration-form');
  if (!dataNode || !dialog || !form) return;

  let programs = [];
  try { programs = JSON.parse(dataNode.textContent || '[]'); } catch (_) { return; }
  const bySlug = new Map(programs.map(program => [program.slug, program]));
  const sessionSelect = document.getElementById('camp-registration-session');
  const priceSelect = document.getElementById('camp-registration-price');
  const status = document.getElementById('camp-registration-status');
  const submit = form.querySelector('[type="submit"]');
  let requestId = '';

  function text(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value;
    return node;
  }
  function infoSection(title, values, className = '') {
    if (!Array.isArray(values) || !values.length) return null;
    const section = document.createElement('section'); section.className = `camp-info-section ${className}`.trim();
    section.append(text('h3', '', title));
    const list = document.createElement('ul');
    values.forEach(value => list.append(text('li', '', value)));
    section.append(list); return section;
  }
  function showProgramInfo(program) {
    const details = program.program_data || {};
    const content = document.createElement('div'); content.className = 'camp-info-body';
    const detailsColumn = document.createElement('div'); detailsColumn.className = 'camp-info-details';
    const flyerColumn = document.createElement('div'); flyerColumn.className = 'camp-info-flyer-column';
    const category = program.category === 'camp' ? 'CAMP' : 'CLINIC';
    const title = text('h2', '', program.name); title.id = 'camp-info-title';
    detailsColumn.append(text('p', 'eyebrow', category), title);
    if (details.flyer_url) {
      const image = document.createElement('img'); image.className = 'camp-info-flyer'; image.src = details.flyer_url;
      image.alt = `${program.name} flyer`; flyerColumn.append(image);
    } else {
      const art = document.createElement('div'); art.className = 'program-art camp-info-art';
      art.append(text('span', '', 'HF'), text('small', '', 'PLAY · TRAIN · GROW')); flyerColumn.append(art);
    }
    if (program.description) detailsColumn.append(text('p', 'camp-info-description', program.description));
    if (details.age_range) detailsColumn.append(text('p', 'program-audience', details.age_range));
    const sessions = infoSection('Upcoming sessions', details.sessions);
    const activities = infoSection('What we’ll do', details.activities, 'camp-info-activities');
    if (sessions) detailsColumn.append(sessions);
    if (activities) detailsColumn.append(activities);
    if (Array.isArray(details.price_options) && details.price_options.length) {
      const prices = document.createElement('section'); prices.className = 'camp-info-section camp-info-prices';
      prices.append(text('h3', '', 'Registration options'));
      details.price_options.forEach(option => {
        const row = document.createElement('div');
        row.append(text('span', '', option.label));
        row.append(text('strong', '', new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(option.price_cents / 100)));
        prices.append(row);
      });
      detailsColumn.append(prices);
    }
    const notes = infoSection('Important notes', details.notes, 'camp-info-notes');
    const otherDetails = infoSection('Program details', program.details);
    if (notes) detailsColumn.append(notes);
    if (otherDetails) detailsColumn.append(otherDetails);
    if (details.sessions?.length && details.price_options?.length) {
      const register = text('button', 'button', 'Register for this program ↗'); register.type = 'button';
      register.addEventListener('click', () => {
        infoDialog.close();
        document.querySelector(`[data-camp-register="${CSS.escape(program.slug)}"]`)?.click();
      });
      detailsColumn.append(register);
    }
    content.append(detailsColumn, flyerColumn);
    infoContent.replaceChildren(content);
    infoDialog.showModal();
  }

  document.querySelectorAll('[data-camp-info]').forEach(button => button.addEventListener('click', () => {
    const program = bySlug.get(button.dataset.campInfo);
    if (program) showProgramInfo(program);
  }));
  infoDialog.querySelector('.dialog-close').addEventListener('click', () => infoDialog.close());
  infoDialog.addEventListener('click', event => { if (event.target === infoDialog) infoDialog.close(); });

  function fill(select, entries, valueFor, labelFor) {
    select.replaceChildren();
    entries.forEach(entry => {
      const option = document.createElement('option');
      option.value = valueFor(entry); option.textContent = labelFor(entry); select.append(option);
    });
  }

  document.querySelectorAll('[data-camp-register]').forEach(button => button.addEventListener('click', () => {
    const program = bySlug.get(button.dataset.campRegister);
    if (!program) return;
    document.getElementById('camp-registration-title').textContent = `Register for ${program.name}`;
    document.getElementById('camp-registration-slug').value = program.slug;
    fill(sessionSelect, program.program_data.sessions || [], value => value, value => value);
    fill(priceSelect, program.program_data.price_options || [], value => value.label,
      value => `${value.label} · ${new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(value.price_cents / 100)}`);
    requestId = crypto.randomUUID(); status.textContent = ''; submit.disabled = false;
    dialog.showModal();
  }));

  dialog.querySelector('.dialog-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  form.addEventListener('input', () => { requestId = crypto.randomUUID(); });
  form.addEventListener('change', () => { requestId = crypto.randomUUID(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const registration = {
      request_id: requestId,
      service_slug: document.getElementById('camp-registration-slug').value,
      session_label: sessionSelect.value,
      price_label: priceSelect.value,
      guardian_name: document.getElementById('camp-guardian-name').value.trim(),
      guardian_email: document.getElementById('camp-guardian-email').value.trim(),
      guardian_phone: document.getElementById('camp-guardian-phone').value.trim(),
      participant_name: document.getElementById('camp-participant-name').value.trim(),
      participant_grade: document.getElementById('camp-participant-grade').value.trim(),
      waiver_confirmed: document.getElementById('camp-waiver-confirmed').checked
    };
    submit.disabled = true; status.textContent = 'Saving registration and opening secure checkout…';
    try {
      await window.fieldhouseSquare.registerCamp(registration);
    } catch (error) {
      status.textContent = error.message || 'Could not start registration. Please try again.';
      submit.disabled = false;
    }
  });

  if (new URLSearchParams(location.search).get('camp_registration') === 'complete') {
    const notice = document.createElement('p'); notice.className = 'camp-registration-success';
    notice.setAttribute('role', 'status'); notice.textContent = 'Thank you. Your camp registration and Square checkout were submitted. Payment confirmation may take a moment.';
    document.querySelector('#camps-clinics .rental-section-heading')?.after(notice);
  }
})();
