(() => {
  const $ = id => document.getElementById(id);
  let loaded = false;
  let draggedCard = null;
  let dropTarget = null;
  let dropBefore = true;

  async function call(path = '', options = {}) {
    const response = await window.fieldhouseAuth.fetch(`/api/gallery/staff${path}`, options);
    if (response.status === 401) { location.replace('/account?next=admin'); throw new Error('Please sign in again.'); }
    if (response.status === 403) { location.replace('/account'); throw new Error('Admin permission is required.'); }
    if (response.status === 204) return null;
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not process this gallery change.');
    return data;
  }

  function cards() { return [...$('gallery-admin-list').querySelectorAll('.gallery-admin-card')]; }

  function refreshOrderLabels() {
    const orderedCards = cards();
    orderedCards.forEach((card, index) => {
      card.querySelector('.gallery-order-number').textContent = `Photo ${index + 1}`;
      card.querySelector('.gallery-drag-handle').setAttribute('aria-label', `Drag photo ${index + 1} to reorder`);
      card.querySelectorAll('.gallery-order-button').forEach(button => { button.disabled = false; });
      card.querySelector('.gallery-move-up').disabled = index === 0;
      card.querySelector('.gallery-move-down').disabled = index === orderedCards.length - 1;
    });
  }

  function clearDropMarker() {
    cards().forEach(card => card.classList.remove('drop-before', 'drop-after'));
    dropTarget = null;
  }

  async function saveOrder() {
    const orderedCards = cards();
    $('gallery-admin-status').textContent = 'Saving photo order…';
    try {
      await call('/order', {method: 'PUT', body: JSON.stringify({photo_ids: orderedCards.map(card => card.dataset.photoId)})});
      $('gallery-admin-status').textContent = 'Photo order saved. The About Us gallery will use this order.';
    } catch (error) {
      $('gallery-admin-status').textContent = error.message;
      await loadGallery();
    } finally { refreshOrderLabels(); }
  }

  function moveCard(card, direction) {
    const sibling = direction < 0 ? card.previousElementSibling : card.nextElementSibling;
    if (!sibling) return;
    if (direction < 0) sibling.before(card); else sibling.after(card);
    refreshOrderLabels(); saveOrder();
  }

  function renderPhoto(photo) {
    const card = document.createElement('article'); card.className = 'card gallery-admin-card'; card.dataset.photoId = photo.id;
    const thumbnail = document.createElement('img'); thumbnail.className = 'gallery-card-thumbnail'; thumbnail.src = photo.image_url; thumbnail.alt = '';
    const order = document.createElement('div'); order.className = 'gallery-admin-order';
    const handle = document.createElement('span'); handle.className = 'gallery-drag-handle'; handle.textContent = '⠿ Drag to reorder';
    const number = document.createElement('strong'); number.className = 'gallery-order-number';
    const up = document.createElement('button'); up.type = 'button'; up.className = 'gallery-move-up gallery-order-button'; up.textContent = 'Move up';
    const down = document.createElement('button'); down.type = 'button'; down.className = 'gallery-move-down gallery-order-button'; down.textContent = 'Move down';
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'gallery-remove'; remove.textContent = 'Remove';
    const status = document.createElement('p'); status.className = 'gallery-item-status'; status.setAttribute('role', 'status');
    up.addEventListener('click', () => moveCard(card, -1)); down.addEventListener('click', () => moveCard(card, 1));
    const dragMove = event => {
      if (!draggedCard) return;
      if (event.clientY < 70) window.scrollBy(0, -18);
      if (event.clientY > window.innerHeight - 70) window.scrollBy(0, 18);
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.gallery-admin-card');
      clearDropMarker();
      if (!target || target === draggedCard) return;
      dropTarget = target;
      dropBefore = event.clientY < target.getBoundingClientRect().top + target.offsetHeight / 2;
      target.classList.add(dropBefore ? 'drop-before' : 'drop-after');
    };
    const dragEnd = () => {
      if (!draggedCard) return;
      window.removeEventListener('pointermove', dragMove);
      window.removeEventListener('pointerup', dragEnd);
      window.removeEventListener('pointercancel', cancelDrag);
      const originalOrder = cards().map(item => item.dataset.photoId).join(',');
      if (dropTarget) {
        if (dropBefore) dropTarget.before(draggedCard); else dropTarget.after(draggedCard);
      }
      draggedCard.classList.remove('is-dragging'); draggedCard = null; clearDropMarker(); refreshOrderLabels();
      if (cards().map(item => item.dataset.photoId).join(',') !== originalOrder) saveOrder();
    };
    const cancelDrag = () => {
      window.removeEventListener('pointermove', dragMove);
      window.removeEventListener('pointerup', dragEnd);
      window.removeEventListener('pointercancel', cancelDrag);
      card.classList.remove('is-dragging'); draggedCard = null; clearDropMarker(); refreshOrderLabels();
    };
    handle.addEventListener('pointerdown', event => {
      event.preventDefault(); draggedCard = card; card.classList.add('is-dragging');
      window.addEventListener('pointermove', dragMove);
      window.addEventListener('pointerup', dragEnd, {once: true});
      window.addEventListener('pointercancel', cancelDrag, {once: true});
    });
    order.append(handle, number, up, down);
    remove.addEventListener('click', async () => {
      if (!confirm(`Remove ${number.textContent.toLowerCase()} from the gallery?`)) return;
      remove.disabled = true; status.textContent = 'Removing…';
      try { await call(`/${photo.id}`, {method: 'DELETE'}); card.remove(); refreshOrderLabels(); $('gallery-admin-status').textContent = 'Photo removed from the gallery.'; }
      catch (error) { status.textContent = error.message; remove.disabled = false; }
    });
    card.append(thumbnail, order, remove, status); return card;
  }

  async function loadGallery() {
    $('gallery-admin-status').textContent = 'Loading gallery…';
    try {
      const photos = await call();
      $('gallery-admin-list').replaceChildren(...photos.map(renderPhoto));
      refreshOrderLabels();
      $('gallery-admin-status').textContent = `${photos.length} ${photos.length === 1 ? 'photo' : 'photos'} in the About Us gallery.`;
      loaded = true;
    } catch (error) { $('gallery-admin-status').textContent = error.message; }
  }

  function optimizeImage(file) {
    return new Promise((resolve, reject) => {
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return reject(new Error('Choose a JPEG, PNG, or WebP image.'));
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('The selected image could not be read.'));
      reader.onload = () => {
        const source = new Image();
        source.onerror = () => reject(new Error('The selected file is not a readable image.'));
        source.onload = () => {
          const scale = Math.min(1, 2200 / Math.max(source.naturalWidth, source.naturalHeight));
          const canvas = document.createElement('canvas');
          canvas.width = Math.max(1, Math.round(source.naturalWidth * scale));
          canvas.height = Math.max(1, Math.round(source.naturalHeight * scale));
          canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
          const data = canvas.toDataURL('image/jpeg', .84);
          if (data.length > 5_500_000) reject(new Error('This image is still too large after optimization. Choose a smaller file.'));
          else resolve(data);
        };
        source.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  $('gallery-upload-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget, button = form.querySelector('button[type=submit]');
    const file = $('gallery-file').files[0];
    if (!file) return;
    button.disabled = true; $('gallery-upload-status').textContent = 'Optimizing photo…';
    try {
      const image_data = await optimizeImage(file);
      $('gallery-upload-status').textContent = 'Uploading photo…';
      await call('', {method: 'POST', body: JSON.stringify({image_data})});
      form.reset(); $('gallery-upload-status').textContent = 'Photo added.'; await loadGallery();
      $('gallery-upload-panel').open = false;
    } catch (error) { $('gallery-upload-status').textContent = error.message; }
    finally { button.disabled = false; }
  });

  window.addEventListener('fieldhouse:gallery-open', () => { if (!loaded) loadGallery(); });
})();
