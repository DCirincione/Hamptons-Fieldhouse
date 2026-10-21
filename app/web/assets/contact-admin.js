(() => {
  const list = document.getElementById('contact-admin-list');
  const status = document.getElementById('contact-admin-status');
  let loaded = false;
  let generation = 0;
  let messages = [];
  let filter = 'all';

  const date = value => new Date(value).toLocaleString('en-US', {
    timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short'
  });

  function messageCard(message) {
    const card = document.createElement('details'); card.className = 'card contact-admin-card';
    card.dataset.state = message.read_at ? 'read' : 'unread';
    const heading = document.createElement('summary'); heading.className = 'contact-admin-heading';
    const name = document.createElement('h3'); name.textContent = `${message.first_name} ${message.last_name}`;
    const sent = document.createElement('time'); sent.dateTime = message.created_at; sent.textContent = date(message.created_at);
    const badge = document.createElement('span'); badge.className = `contact-message-state ${card.dataset.state}`; badge.textContent = message.read_at ? 'Read' : 'Unread';
    const meta = document.createElement('span'); meta.className = 'contact-admin-summary-meta'; meta.append(badge, sent);
    heading.append(name, meta);
    const content = document.createElement('div'); content.className = 'contact-admin-content';
    const contact = document.createElement('div'); contact.className = 'contact-admin-details';
    const email = document.createElement('a'); email.href = `mailto:${message.email}`; email.textContent = message.email;
    const phone = document.createElement('a'); phone.href = `tel:${message.phone_number}`; phone.textContent = message.phone_number;
    contact.append(email, phone);
    const body = document.createElement('p'); body.className = 'contact-admin-message'; body.textContent = message.message;
    content.append(contact, body); card.append(heading, content);
    card.addEventListener('toggle', async () => {
      if (!card.open || message.read_at) return;
      try {
        const response = await window.fieldhouseAuth.fetch(`/api/contact-messages/staff/${message.id}`, {method: 'PATCH', body: JSON.stringify({is_read: true})});
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The message status could not be updated.');
        message.read_at = data.read_at || new Date().toISOString(); card.dataset.state = 'read'; badge.className = 'contact-message-state read'; badge.textContent = 'Read';
        if (filter === 'unread') render();
      } catch (error) { status.textContent = error.message; }
    });
    return card;
  }

  function render() {
    const visible = messages.filter(message => filter === 'all' || (filter === 'read') === Boolean(message.read_at));
    list.replaceChildren(...visible.map(messageCard));
    status.textContent = visible.length ? `${visible.length} ${filter === 'all' ? 'contact message' : `${filter} message`}${visible.length === 1 ? '' : 's'}.` : `No ${filter === 'all' ? 'contact' : filter} messages.`;
  }

  async function load(force = false) {
    if (loaded && !force) return;
    const current = ++generation; status.textContent = 'Loading contact messages…'; list.replaceChildren();
    try {
      const response = await window.fieldhouseAuth.fetch('/api/contact-messages/staff');
      if (response.status === 401) return location.replace('/account?next=admin');
      if (response.status === 403) return location.replace('/account');
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Contact messages could not be loaded.');
      if (current !== generation) return;
      loaded = true; messages = data; render();
    } catch (error) { if (current === generation) status.textContent = error.message; }
  }

  window.addEventListener('fieldhouse:contacts-open', () => {
    filter = 'all';
    document.querySelectorAll('[data-contact-filter]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.contactFilter === 'all')));
    if (loaded) render();
    load(loaded);
  });
  document.querySelectorAll('[data-contact-filter]').forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.contactFilter;
    document.querySelectorAll('[data-contact-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    render();
  }));
})();
