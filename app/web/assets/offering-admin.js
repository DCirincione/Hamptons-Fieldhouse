(() => {
  const $ = id => document.getElementById(id);
  const status = $('offering-admin-status');
  let loaded = false, loading = false;

  function label(text, control) {
    const element = document.createElement('label');
    element.append(text, control);
    return element;
  }
  function input(type, value, options = {}) {
    const element = document.createElement('input');
    element.type = type;
    if (value !== undefined && value !== null) element.value = value;
    if (options.min !== undefined) element.min = options.min;
    if (options.max !== undefined) element.max = options.max;
    if (options.step !== undefined) element.step = options.step;
    if (options.maxLength !== undefined) element.maxLength = options.maxLength;
    if (options.required) element.required = true;
    return element;
  }
  function textarea(value, rows = 3) {
    const element = document.createElement('textarea');
    element.value = value || ''; element.rows = rows;
    return element;
  }
  function serviceSlug(name) {
    return name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80).replace(/-+$/g, '');
  }
  async function request(url, options = {}) {
    const response = await window.fieldhouseAuth.fetch(url, options);
    if (response.status === 401) { location.replace('/account?next=admin'); throw new Error('Please sign in again.'); }
    if (response.status === 403) { location.replace('/account'); throw new Error('Admin permission is required.'); }
    const responseText = await response.text();
    let result = {};
    if (responseText) {
      try { result = JSON.parse(responseText); }
      catch { throw new Error(`Service request failed (${response.status}): ${responseText.slice(0, 240)}`); }
    }
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save service settings.');
    return result;
  }
  function resourcesEditor(selected = []) {
    const fieldset = document.createElement('fieldset'); fieldset.className = 'offering-resource-options';
    const legend = document.createElement('legend'); legend.textContent = 'Calendar spaces this service uses'; fieldset.append(legend);
    const choices = [['field', 'Full field'], ['backspace', 'Speed & agility + batting cage'], ['party-area', 'Party area']];
    choices.forEach(([value, text]) => {
      const checkbox = input('checkbox'); checkbox.value = value; checkbox.checked = selected.includes(value);
      const choice = document.createElement('label'); choice.append(checkbox, text); fieldset.append(choice);
    });
    const note = document.createElement('small');
    note.textContent = 'Services assigned to the full field share its availability. A quarter-field rental will reserve the full-field calendar space for now.';
    fieldset.append(note);
    return fieldset;
  }
  function serviceCards(list) { return [...list.querySelectorAll(':scope > .offering-admin-card')]; }
  function refreshServiceOrderLabels(list) {
    const cards = serviceCards(list);
    cards.forEach((card, index) => {
      card.dataset.sortOrder = (index + 1) * 10;
      card.querySelector('.offering-move-up').disabled = index === 0;
      card.querySelector('.offering-move-down').disabled = index === cards.length - 1;
    });
  }
  async function saveServiceOrder(list) {
    status.textContent = 'Saving service order…';
    try {
      await request('/api/bookings/staff/offerings-order', {
        method: 'PUT', body: JSON.stringify({slugs: serviceCards(list).map(card => card.dataset.slug)})
      });
      status.textContent = 'Service order saved.';
    } catch (error) {
      status.textContent = error.message;
      await refreshCatalog();
    } finally { refreshServiceOrderLabels(list); }
  }
  function moveServiceCard(card, direction) {
    const sibling = direction < 0 ? card.previousElementSibling : card.nextElementSibling;
    if (!sibling) return;
    if (direction < 0) sibling.before(card); else sibling.after(card);
    const list = card.parentElement;
    refreshServiceOrderLabels(list); saveServiceOrder(list);
  }
  function serviceOrderControls(card, item) {
    const controls = document.createElement('span'); controls.className = 'offering-order-controls';
    const up = document.createElement('button'); up.type = 'button'; up.className = 'offering-move-up offering-order-button'; up.textContent = '↑'; up.setAttribute('aria-label', `Move ${item.name} up`); up.title = 'Move up';
    const down = document.createElement('button'); down.type = 'button'; down.className = 'offering-move-down offering-order-button'; down.textContent = '↓'; down.setAttribute('aria-label', `Move ${item.name} down`); down.title = 'Move down';
    up.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); moveServiceCard(card, -1); });
    down.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); moveServiceCard(card, 1); });
    controls.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); });
    const arrows = document.createElement('span'); arrows.className = 'offering-order-arrows';
    arrows.append(up, down);
    controls.append(arrows);
    return controls;
  }
  function programEditor(value = {}, slug = null) {
    const data = value || {};
    const panel = document.createElement('details'); panel.className = 'offering-program-editor';
    const summary = document.createElement('summary'); summary.textContent = 'Program details, sessions & registration';
    const grid = document.createElement('div'); grid.className = 'offering-admin-fields';
    const flyerFile = input('file'); flyerFile.accept = 'image/jpeg,image/png,image/webp';
    const flyerPreview = document.createElement('img'); flyerPreview.className = 'offering-flyer-preview'; flyerPreview.alt = 'Current program flyer';
    flyerPreview.hidden = !data.flyer_url;
    if (data.flyer_url) flyerPreview.src = data.flyer_url;
    const uploadFlyer = document.createElement('button'); uploadFlyer.type = 'button'; uploadFlyer.className = 'staff-utility offering-flyer-upload';
    uploadFlyer.textContent = data.flyer_url ? 'Replace flyer' : 'Upload flyer'; uploadFlyer.disabled = !slug; uploadFlyer.hidden = !slug;
    const flyerStatus = document.createElement('small'); flyerStatus.className = 'offering-flyer-status'; flyerStatus.setAttribute('role', 'status');
    const flyerField = document.createElement('div'); flyerField.className = 'offering-flyer-field';
    const flyerLabel = document.createElement('label'); flyerLabel.textContent = 'Flyer image'; flyerLabel.append(flyerFile);
    const flyerHelp = document.createElement('small'); flyerHelp.textContent = slug ? 'JPEG, PNG, or WebP. Uploading a new flyer replaces the current one.' : 'Choose a JPEG, PNG, or WebP flyer now. It will upload when you create the camp or clinic.';
    flyerField.append(flyerLabel, flyerHelp, uploadFlyer, flyerStatus, flyerPreview);
    let localFlyerPreview = '';
    flyerFile.addEventListener('change', () => {
      const file = flyerFile.files?.[0];
      if (!file) return;
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { flyerStatus.textContent = 'Choose a JPEG, PNG, or WebP flyer image.'; return; }
      if (localFlyerPreview) URL.revokeObjectURL(localFlyerPreview);
      localFlyerPreview = URL.createObjectURL(file);
      flyerPreview.src = localFlyerPreview; flyerPreview.hidden = false;
      if (!slug) {
        flyerStatus.textContent = 'Flyer preview. It will upload when you create the camp or clinic.';
        return;
      }
      uploadFlyer.disabled = true; uploadFlyer.textContent = 'Uploading flyer…';
      flyerStatus.textContent = 'Uploading your flyer…';
      uploadSelectedFlyer(slug).catch(error => {
        flyerStatus.textContent = `${error.message} You can retry with the Upload flyer button.`;
      }).finally(() => {
        uploadFlyer.disabled = false;
        uploadFlyer.textContent = data.flyer_url ? 'Replace flyer' : 'Upload flyer';
      });
    });
    const age = input('text', data.age_range || '', {maxLength: 100}); age.placeholder = 'Grades 2–6';
    const sessions = textarea((data.sessions || []).join('\n'), 3);
    const activities = textarea((data.activities || []).join('\n'), 3);
    const prices = textarea((data.price_options || []).map(option => `${option.label} | ${(option.price_cents / 100).toFixed(2)}`).join('\n'), 3);
    prices.addEventListener('input', () => prices.setCustomValidity(''));
    const notes = textarea((data.notes || []).join('\n'), 2);
    function addHelp(control, text) { const help = document.createElement('small'); help.textContent = text; control.parentElement.append(help); }
    const sessionsLabel = label('Session dates (one per line)', sessions); addHelp(sessions, 'Add future dates before publishing. Example: July 13–17, 2027.');
    const activitiesLabel = label('Activities (one per line)', activities);
    const pricesLabel = label('Registration options and price', prices); addHelp(prices, 'One per line, using “Half day | 250” or “Full day | 375”.');
    const notesLabel = label('Important notes (one per line)', notes);
    grid.append(flyerField, label('Age or grade range', age), sessionsLabel, activitiesLabel, pricesLabel, notesLabel);
    panel.append(summary, grid);
    async function optimize(file) {
      if (!file || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Choose a JPEG, PNG, or WebP flyer image.');
      const source = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('The selected flyer could not be read.')); reader.readAsDataURL(file);
      });
      const image = await new Promise((resolve, reject) => {
        const element = new Image(); element.onload = () => resolve(element); element.onerror = () => reject(new Error('The selected file is not a readable image.')); element.src = source;
      });
      const scale = Math.min(1, 1800 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement('canvas'); canvas.width = Math.round(image.naturalWidth * scale); canvas.height = Math.round(image.naturalHeight * scale);
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
      const optimized = canvas.toDataURL('image/jpeg', .84);
      if (optimized.length > 5_500_000) throw new Error('This flyer is still too large. Choose a smaller image.');
      return optimized;
    }
    async function uploadSelectedFlyer(serviceSlug) {
      const file = flyerFile.files?.[0];
      if (!file) return false;
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Choose a JPEG, PNG, or WebP flyer image.');
      flyerStatus.textContent = 'Preparing flyer…';
      const image_data = await optimize(file); flyerStatus.textContent = 'Uploading flyer…';
      const result = await request(`/api/bookings/staff/offerings/${encodeURIComponent(serviceSlug)}/flyer`, {method: 'POST', body: JSON.stringify({image_data})});
      data.flyer_url = result.flyer_url; data.flyer_storage_path = result.flyer_storage_path;
      if (localFlyerPreview) { URL.revokeObjectURL(localFlyerPreview); localFlyerPreview = ''; }
      flyerPreview.src = result.flyer_url; flyerPreview.hidden = false; uploadFlyer.textContent = 'Replace flyer'; flyerFile.value = '';
      flyerStatus.textContent = 'Flyer uploaded.';
      return true;
    }
    uploadFlyer.addEventListener('click', async () => {
      if (!slug || !flyerFile.files?.[0]) { flyerStatus.textContent = 'Choose an image first.'; return; }
      uploadFlyer.disabled = true;
      try {
        await uploadSelectedFlyer(slug);
      } catch (error) { flyerStatus.textContent = error.message; }
      finally { uploadFlyer.disabled = false; }
    });
    return {
      panel,
      hasSelectedFlyer: () => Boolean(flyerFile.files?.[0]),
      uploadSelectedFlyer,
      reportValidity: () => prices.reportValidity(),
      read() {
        const priceLines = prices.value.split('\n').map(line => line.trim()).filter(Boolean);
        const options = [];
        let invalid = false;
        for (const line of priceLines) {
          const match = line.match(/^(.+?)\s*\|\s*(\d+(?:\.\d{1,2})?)$/);
          if (!match || Number(match[2]) > 100000) { invalid = true; break; }
          options.push({label: match[1].trim(), price_cents: Math.round(Number(match[2]) * 100)});
        }
        prices.setCustomValidity(invalid ? 'Use one option per line in the format “Half day | 250”.' : '');
        return {
          valid: !invalid,
          data: {
            flyer_url: data.flyer_url || '', flyer_storage_path: data.flyer_storage_path || '', age_range: age.value.trim(),
            sessions: sessions.value.split('\n').map(line => line.trim()).filter(Boolean),
            activities: activities.value.split('\n').map(line => line.trim()).filter(Boolean),
            price_options: options,
            notes: notes.value.split('\n').map(line => line.trim()).filter(Boolean)
          }
        };
      }
    };
  }
  function render(item) {
    const card = document.createElement('details'); card.className = 'card offering-admin-card';
    card.dataset.slug = item.slug; card.dataset.sortOrder = item.sort_order;
    const summary = document.createElement('summary'); summary.className = 'offering-admin-summary';
    const title = document.createElement('strong'); title.textContent = item.name;
    const flyerUrl = item.program_data?.flyer_url;
    let flyerThumbnail = null;
    if (flyerUrl && ['camp', 'clinic', 'event'].includes(item.category)) {
      flyerThumbnail = document.createElement('img'); flyerThumbnail.className = 'offering-summary-flyer'; flyerThumbnail.src = flyerUrl; flyerThumbnail.alt = `${item.name} flyer`;
      flyerThumbnail.addEventListener('error', () => { flyerThumbnail.hidden = true; });
    }
    const meta = document.createElement('span');
    meta.className = 'offering-admin-meta';
    const categoryName = item.category === 'field_rental' ? 'Field rental' : item.category === 'birthday' ? 'Birthday party' : item.category === 'camp' ? 'Camp' : item.category === 'clinic' ? 'Clinic' : item.category;
    const priceText = item.price_cents == null ? '' : ` · ${new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(item.price_cents / 100)}`;
    const publishedText = item.published ? 'Published' : 'Hidden';
    meta.textContent = `${categoryName}${priceText} · ${publishedText}`;
    summary.append(serviceOrderControls(card, item));
    if (flyerThumbnail) summary.append(flyerThumbnail);
    summary.append(title, meta);

    const form = document.createElement('form'); form.className = 'offering-admin-form';
    const name = input('text', item.name, {maxLength: 120, required: true});
    const description = textarea(item.description, 3); description.maxLength = 1000;
    const details = textarea((item.details || []).join('\n'), 5); details.setAttribute('aria-describedby', `offering-help-${item.slug}`);
    const program = ['camp', 'clinic', 'event'].includes(item.category);
    const bookable = !program;
    const programData = program ? programEditor(item.program_data, item.slug) : null;
    const price = input('number', item.price_cents == null ? '' : (item.price_cents / 100).toFixed(2), {min: 0, max: 100000, step: '0.01', required: bookable});
    const duration = input('number', item.duration_minutes || 60, {min: 15, max: 720, step: 15, required: true});
    const capacity = input('number', item.capacity, {min: 1, max: 500});
    const discount = input('number', ((item.own_food_discount_cents || 0) / 100).toFixed(2), {min: 0, max: 10000, step: '0.01'});
    const published = input('checkbox'); published.checked = item.published;
    const grid = document.createElement('div'); grid.className = 'offering-admin-fields';
    const priceLabel = label('Price (USD)', price); priceLabel.hidden = program;
    const durationLabel = label('Duration (minutes)', duration); durationLabel.hidden = program;
    const capacityLabel = label('Included capacity', capacity); capacityLabel.hidden = item.category === 'field_rental' || program;
    const discountLabel = label('Bring-your-own-food discount (USD)', discount); discountLabel.hidden = item.category !== 'birthday';
    grid.append(label('Service Name', name), priceLabel, label('Description', description), durationLabel,
      capacityLabel, discountLabel, label('Details (one item per line)', details));
    const detailsWrap = grid.lastElementChild; detailsWrap.classList.add('offering-admin-details-field');
    const help = document.createElement('small'); help.id = `offering-help-${item.slug}`; help.textContent = 'Leave blank to show no bullet points.'; detailsWrap.append(help);
    let resources = null;
    if (item.category === 'field_rental') {
      resources = resourcesEditor(item.resources || []);
      grid.append(resources);
    }
    if (programData) form.append(grid, programData.panel);
    const publishedLabel = document.createElement('label'); publishedLabel.className = 'offering-admin-published';
    const publishedTextNode = document.createElement('span');
    publishedTextNode.textContent = program ? 'Show this camp or clinic' : 'Show this service on the booking page';
    publishedLabel.append(publishedTextNode, published);
    const submit = document.createElement('button'); submit.type = 'submit'; submit.className = 'button'; submit.textContent = 'Save changes';
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'offering-remove-button'; remove.textContent = 'Remove from catalog';
    const actions = document.createElement('div'); actions.className = 'offering-admin-actions'; actions.append(submit, remove);
    const feedback = document.createElement('p'); feedback.className = 'offering-admin-feedback'; feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
    if (!programData) form.append(grid);
    form.append(publishedLabel, actions, feedback);
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Remove “${item.name}” from the catalog? Customers will no longer see it, and existing booking records will be kept.`)) return;
      remove.disabled = true; submit.disabled = true; feedback.textContent = 'Removing…';
      try {
        await request(`/api/bookings/staff/offerings/${encodeURIComponent(item.slug)}`, {method: 'DELETE'});
        await refreshCatalog();
        status.textContent = `${item.name} was removed from the catalog. Existing booking records were kept.`;
      } catch (error) {
        feedback.textContent = error.message; status.textContent = error.message;
        remove.disabled = false; submit.disabled = false;
      }
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const campData = programData ? programData.read() : {valid: true, data: {}};
      if (!campData.valid) { programData.reportValidity(); return; }
      const values = {
        name: name.value.trim(), description: description.value.trim(),
        details: details.value.split('\n').map(line => line.trim()).filter(Boolean),
        price_cents: bookable ? Math.round(Number(price.value) * 100) : null,
        duration_minutes: Number(duration.value), capacity: capacity.value === '' ? null : Number(capacity.value),
        own_food_discount_cents: Math.round(Number(discount.value) * 100),
        sort_order: Number(card.dataset.sortOrder), published: published.checked,
        resources: resources ? [...resources.querySelectorAll('input:checked')].map(element => element.value) : (item.resources || []),
        program_data: campData.data
      };
      submit.disabled = true; feedback.textContent = 'Saving…';
      try {
        await request(`/api/bookings/staff/offerings/${encodeURIComponent(item.slug)}`, {method: 'PUT', body: JSON.stringify(values)});
        Object.assign(item, values);
        card.dataset.sortOrder = item.sort_order;
        title.textContent = item.name;
        const currentPrice = item.price_cents == null ? '' : ` · ${new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(item.price_cents / 100)}`;
        meta.textContent = `${categoryName}${currentPrice} · ${item.published ? 'Published' : 'Hidden'}`;
        feedback.textContent = 'Changes saved. The public page will show the updated details.'; status.textContent = 'Service settings saved.';
      } catch (error) { feedback.textContent = error.message; status.textContent = error.message; }
      finally { submit.disabled = false; }
    });
    card.append(summary, form);
    return card;
  }
  function renderExtra(item) {
    const names = {'additional-child': 'Additional child', 'pizza-with-toppings': 'Additional pizza with toppings'};
    const form = document.createElement('form'); form.className = 'offering-extra-form';
    const amount = input('number', (item.unit_price_cents / 100).toFixed(2), {min: 0, max: 10000, step: '0.01', required: true});
    const submit = document.createElement('button'); submit.type = 'submit'; submit.className = 'staff-utility'; submit.textContent = 'Save';
    const feedback = document.createElement('span'); feedback.className = 'offering-extra-feedback'; feedback.setAttribute('role', 'status');
    form.append(label(names[item.slug] || item.name, amount), submit, feedback);
    form.addEventListener('submit', async event => {
      event.preventDefault(); submit.disabled = true; feedback.textContent = 'Saving…';
      try {
        const unit_price_cents = Math.round(Number(amount.value) * 100);
        await request(`/api/bookings/staff/extras/${encodeURIComponent(item.slug)}`, {method: 'PUT', body: JSON.stringify({unit_price_cents})});
        item.unit_price_cents = unit_price_cents; feedback.textContent = 'Saved'; status.textContent = 'Party add-on price saved.';
      } catch (error) { feedback.textContent = error.message; status.textContent = error.message; }
      finally { submit.disabled = false; }
    });
    return form;
  }
  function renderRegistration(item) {
    const card = document.createElement('details'); card.className = 'camp-registration-admin-card';
    const summary = document.createElement('summary');
    const primary = document.createElement('strong'); primary.textContent = item.participant_name;
    const meta = document.createElement('span');
    const statusText = item.status === 'paid' ? 'Paid' : item.status === 'payment_failed' ? 'Payment failed' : 'Awaiting payment';
    const amount = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(item.amount_cents / 100);
    meta.textContent = `${item.offerings?.name || 'Camp'} · ${item.session_label} · ${statusText} · ${amount}`;
    summary.append(primary, meta);
    const content = document.createElement('div'); content.className = 'camp-registration-admin-content';
    const participant = document.createElement('p'); participant.textContent = `Grade: ${item.participant_grade} · Option: ${item.price_label}`;
    const guardian = document.createElement('p'); guardian.textContent = `Parent / guardian: ${item.guardian_name}`;
    const contact = document.createElement('div'); contact.className = 'camp-registration-contact';
    const email = document.createElement('a'); email.href = `mailto:${item.guardian_email}`; email.textContent = item.guardian_email;
    const phone = document.createElement('a'); phone.href = `tel:${item.guardian_phone}`; phone.textContent = item.guardian_phone;
    contact.append(email, phone);
    const date = document.createElement('small'); date.textContent = item.created_at ? `Registered ${new Date(item.created_at).toLocaleString()}` : '';
    content.append(participant, guardian, contact, date); card.append(summary, content);
    return card;
  }
  function appendCreateForm(category, button) {
    const group = button.closest('.offering-admin-group');
    let panel = group.querySelector('.offering-create-panel');
    if (panel) { panel.open = !panel.open; return; }
    panel = document.createElement('details'); panel.open = true; panel.className = 'card offering-create-panel';
    const summary = document.createElement('summary');
    summary.textContent = category === 'field_rental' ? 'New field rental' : category === 'birthday' ? 'New birthday package' : 'New camp or clinic';
    const form = document.createElement('form'); form.className = 'offering-admin-form';
    const name = input('text', '', {maxLength: 120, required: true});
    const description = textarea('', 3); description.maxLength = 1000;
    const details = textarea('', 5);
    const isRental = category === 'field_rental';
    const isBirthday = category === 'birthday';
    const isBookable = isRental || isBirthday;
    const programData = isBookable ? null : programEditor({});
    const price = input('number', '', {min: 0, max: 100000, step: '0.01', required: isBookable});
    const duration = input('number', isBirthday ? 90 : 60, {min: isBirthday ? 75 : 15, max: 720, step: 15, required: true});
    const capacity = input('number', isBirthday ? 12 : '', {min: 1, max: 500});
    const discount = input('number', isBirthday ? '50.00' : '0.00', {min: 0, max: 10000, step: '0.01'});
    const published = input('checkbox'); published.checked = isBookable;
    let categoryInput;
    if (isRental || isBirthday) categoryInput = category;
    else {
      categoryInput = document.createElement('select');
      [['camp', 'Camp'], ['clinic', 'Clinic']].forEach(([value, text]) => { const option = document.createElement('option'); option.value = value; option.textContent = text; categoryInput.append(option); });
    }
    const grid = document.createElement('div'); grid.className = 'offering-admin-fields';
    const priceLabel = label('Price (USD)', price); priceLabel.hidden = !isBookable;
    const durationLabel = label('Duration (minutes)', duration); durationLabel.hidden = !isBookable;
    const capacityLabel = label('Included capacity', capacity); capacityLabel.hidden = !isBirthday;
    const discountLabel = label('Bring-your-own-food discount (USD)', discount); discountLabel.hidden = !isBirthday;
    if (typeof categoryInput !== 'string') grid.append(label('Program type', categoryInput));
    const nameLabel = label('Service Name', name);
    const nameHelp = document.createElement('small'); nameHelp.textContent = 'A service ID is generated automatically from this name.'; nameLabel.append(nameHelp);
    grid.append(nameLabel,
      label('Description', description), priceLabel, durationLabel, capacityLabel, discountLabel,
      label('Details (one item per line)', details));
    const detailsWrap = grid.lastElementChild; detailsWrap.classList.add('offering-admin-details-field');
    let spacePicker = null;
    if (isRental) { spacePicker = resourcesEditor([]); grid.append(spacePicker); }
    const publishedLabel = document.createElement('label'); publishedLabel.className = 'offering-admin-published';
    const publishedText = document.createElement('span'); publishedText.textContent = isBookable ? 'Show this service on the booking page' : 'Show this camp or clinic';
    publishedLabel.append(publishedText, published);
    const submit = document.createElement('button'); submit.type = 'submit'; submit.className = 'button'; submit.textContent = 'Create service';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'offering-create-cancel'; cancel.textContent = 'Cancel';
    cancel.addEventListener('click', () => panel.remove());
    const feedback = document.createElement('p'); feedback.className = 'offering-admin-feedback'; feedback.setAttribute('role', 'status');
    form.append(grid);
    if (programData) form.append(programData.panel);
    const actions = document.createElement('div'); actions.className = 'offering-admin-actions'; actions.append(submit, cancel);
    form.append(publishedLabel, actions, feedback);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const campData = programData ? programData.read() : {valid: true, data: {}};
      if (!campData.valid) { programData.reportValidity(); return; }
      const slug = serviceSlug(name.value);
      if (!slug) { name.setCustomValidity('Enter a name with at least one letter or number.'); name.reportValidity(); name.setCustomValidity(''); return; }
      submit.disabled = true; cancel.disabled = true; feedback.textContent = 'Creating…';
      const targetList = category === 'field_rental' ? $('offering-admin-field-rentals') : category === 'birthday' ? $('offering-admin-birthdays') : $('offering-admin-camps');
      const nextOrder = serviceCards(targetList).reduce((max, card) => Math.max(max, Number(card.dataset.sortOrder) || 0), 0) + 10;
      const values = {
        slug, category: typeof categoryInput === 'string' ? categoryInput : categoryInput.value,
        name: name.value.trim(), description: description.value.trim(),
        details: details.value.split('\n').map(line => line.trim()).filter(Boolean),
        price_cents: isBookable ? Math.round(Number(price.value) * 100) : null,
        duration_minutes: Number(duration.value), capacity: isBirthday ? Number(capacity.value) : null, published: published.checked,
        sort_order: nextOrder, own_food_discount_cents: isBirthday ? Math.round(Number(discount.value) * 100) : 0,
        resources: spacePicker ? [...spacePicker.querySelectorAll('input:checked')].map(element => element.value) : [],
        program_data: campData.data
      };
      try {
        await request('/api/bookings/staff/offerings', {method: 'POST', body: JSON.stringify(values)});
      } catch (error) { feedback.textContent = error.message; status.textContent = error.message; submit.disabled = false; cancel.disabled = false; return; }
      let flyerError = null;
      const hasFlyer = Boolean(programData?.hasSelectedFlyer());
      if (hasFlyer) {
        try { await programData.uploadSelectedFlyer(values.slug); }
        catch (error) { flyerError = error; }
      }
      try {
        await refreshCatalog();
        const created = [...document.querySelectorAll('.offering-admin-card')].find(card => card.querySelector('.offering-admin-summary strong')?.textContent === values.name);
        if (created) created.open = true;
        panel.remove();
        if (flyerError) {
          status.textContent = `Service created, but the flyer upload failed: ${flyerError.message} Open the service to retry the upload.`;
        } else {
          status.textContent = hasFlyer ? 'Camp or clinic created and flyer uploaded.' : 'Service created.';
        }
      } catch (error) { feedback.textContent = `Service created, but the list could not refresh: ${error.message}`; status.textContent = feedback.textContent; }
      finally { submit.disabled = false; cancel.disabled = false; }
    });
    panel.append(summary, form); group.insertBefore(panel, group.querySelector('.offering-admin-list'));
  }
  async function refreshCatalog() {
    const [items, extras, registrations] = await Promise.all([
      request('/api/bookings/staff/offerings'), request('/api/bookings/staff/extras'), request('/api/bookings/staff/camp-registrations')
    ]);
    const fields = items.filter(item => item.category === 'field_rental');
    const camps = items.filter(item => ['camp', 'clinic', 'event'].includes(item.category));
    const parties = items.filter(item => item.category === 'birthday');
    $('offering-admin-field-rentals').replaceChildren(...fields.map(render));
    $('offering-admin-camps').replaceChildren(...camps.map(render));
    $('offering-admin-camps-empty').hidden = camps.length > 0;
    $('offering-admin-birthdays').replaceChildren(...parties.map(render));
    [$('offering-admin-field-rentals'), $('offering-admin-camps'), $('offering-admin-birthdays')].forEach(refreshServiceOrderLabels);
    $('offering-extra-list').replaceChildren(...extras.map(renderExtra));
    $('camp-registration-admin-list').replaceChildren(...registrations.map(renderRegistration));
    $('camp-registration-count').textContent = `${registrations.length} recent registration${registrations.length === 1 ? '' : 's'}`;
    $('camp-registration-admin-status').textContent = registrations.length ? '' : 'No camp registrations yet.';
    loaded = true;
    status.textContent = `${fields.length} field rentals · ${camps.length} camps and clinics · ${parties.length} birthday parties.`;
  }
  async function load() {
    if (loaded || loading) return;
    loading = true; status.textContent = 'Loading services…';
    try { await refreshCatalog(); }
    catch (error) { status.textContent = error.message; }
    finally { loading = false; }
  }
  document.querySelectorAll('.offering-create-trigger').forEach(button => button.addEventListener('click', () => appendCreateForm(button.dataset.createCategory, button)));
  window.addEventListener('fieldhouse:offerings-open', load);
  window.addEventListener('fieldhouse:offerings-refresh', () => { loaded = false; load(); });
})();
