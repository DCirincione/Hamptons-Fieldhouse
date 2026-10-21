(() => {
  const grid = document.getElementById('merch-grid');
  const status = document.getElementById('merch-status');
  const template = document.getElementById('merch-card-template');
  const productDialog = document.getElementById('merch-product-dialog');
  const cartDialog = document.getElementById('merch-cart-dialog');
  const cartCounts = document.querySelectorAll('.merch-cart-count');
  const cartItems = document.getElementById('merch-cart-items');
  const money = value => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(value);
  const storageKey = 'fieldhouse-merch-cart-v1';
  let activeProduct;
  let activeVariant;
  let cart = readCart();

  function readCart() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey));
      return Array.isArray(saved) ? saved : [];
    } catch (_) { return []; }
  }
  function saveCart() {
    try { localStorage.setItem(storageKey, JSON.stringify(cart)); } catch (_) {}
    renderCart();
  }
  function productPrice(product) {
    if (product.price_min == null) return 'Price coming soon';
    return product.price_min === product.price_max ? money(product.price_min) : `${money(product.price_min)}–${money(product.price_max)}`;
  }
  function unique(values) { return [...new Set(values.filter(Boolean))]; }
  function fillSelect(select, values, selected) {
    select.replaceChildren(...values.map(value => {
      const option = document.createElement('option');
      option.value = value; option.textContent = value; option.selected = value === selected;
      return option;
    }));
  }
  function selectedVariant() {
    const color = document.getElementById('merch-color').value;
    const size = document.getElementById('merch-size').value;
    return activeProduct.variants.find(variant => (!color || variant.color === color) && (!size || variant.size === size)) || activeProduct.variants[0];
  }
  function setGallery(variant) {
    const main = document.getElementById('merch-product-image');
    const thumbnails = document.getElementById('merch-thumbnails');
    const images = unique([...(variant.images || []), ...(activeProduct.images || []), variant.image, activeProduct.image]);
    if (!images.length) { main.removeAttribute('src'); main.alt = ''; thumbnails.replaceChildren(); return; }
    main.src = images[0]; main.alt = activeProduct.name;
    thumbnails.replaceChildren(...images.map((url, index) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = `merch-thumbnail${index === 0 ? ' active' : ''}`;
      button.setAttribute('aria-label', `View image ${index + 1} of ${images.length}`);
      const image = document.createElement('img'); image.src = url; image.alt = ''; button.append(image);
      button.addEventListener('click', () => {
        main.src = url;
        thumbnails.querySelectorAll('button').forEach(item => item.classList.toggle('active', item === button));
      });
      return button;
    }));
    thumbnails.hidden = images.length < 2;
  }
  function updateVariant() {
    const colorSelect = document.getElementById('merch-color');
    const sizeSelect = document.getElementById('merch-size');
    const available = activeProduct.variants.filter(variant => !colorSelect.value || variant.color === colorSelect.value);
    const sizes = unique(available.map(variant => variant.size));
    const previousSize = sizeSelect.value;
    fillSelect(sizeSelect, sizes.length ? sizes : ['Standard'], sizes.includes(previousSize) ? previousSize : sizes[0]);
    activeVariant = selectedVariant();
    document.getElementById('merch-product-price').textContent = activeVariant.price == null ? productPrice(activeProduct) : money(Number(activeVariant.price));
    setGallery(activeVariant);
  }
  function openProduct(product) {
    activeProduct = product;
    document.getElementById('merch-product-title').textContent = product.name;
    document.getElementById('merch-quantity').value = 1;
    document.getElementById('merch-add-status').textContent = '';
    const colors = unique(product.variants.map(variant => variant.color));
    fillSelect(document.getElementById('merch-color'), colors.length ? colors : ['Standard'], colors[0]);
    document.getElementById('merch-color-field').hidden = colors.length === 0;
    document.getElementById('merch-size-field').hidden = unique(product.variants.map(variant => variant.size)).length === 0;
    updateVariant(); productDialog.showModal();
  }
  function renderCart() {
    const quantity = cart.reduce((total, item) => total + item.quantity, 0);
    cartCounts.forEach(count => { count.textContent = quantity; });
    cartItems.replaceChildren();
    if (!cart.length) {
      const empty = document.createElement('p'); empty.className = 'merch-cart-empty'; empty.textContent = 'Your cart is empty.'; cartItems.append(empty);
    }
    cart.forEach(item => {
      const row = document.createElement('article'); row.className = 'merch-cart-item';
      if (item.image) { const image = document.createElement('img'); image.src = item.image; image.alt = ''; row.append(image); }
      const details = document.createElement('div');
      const name = document.createElement('h3'); name.textContent = item.name; details.append(name);
      const options = document.createElement('p'); options.textContent = [item.color, item.size].filter(Boolean).join(' · ') || 'Standard'; details.append(options);
      const controls = document.createElement('div'); controls.className = 'merch-cart-controls';
      const minus = document.createElement('button'); minus.type = 'button'; minus.textContent = '−'; minus.setAttribute('aria-label', `Remove one ${item.name}`);
      const count = document.createElement('span'); count.textContent = item.quantity;
      const plus = document.createElement('button'); plus.type = 'button'; plus.textContent = '+'; plus.setAttribute('aria-label', `Add one ${item.name}`);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'merch-remove'; remove.textContent = 'Remove';
      minus.addEventListener('click', () => { item.quantity -= 1; if (item.quantity < 1) cart = cart.filter(entry => entry !== item); saveCart(); });
      plus.addEventListener('click', () => { if (item.quantity < 10) item.quantity += 1; saveCart(); });
      remove.addEventListener('click', () => { cart = cart.filter(entry => entry !== item); saveCart(); });
      controls.append(minus, count, plus, remove); details.append(controls); row.append(details);
      const price = document.createElement('strong'); price.textContent = money(Number(item.price || 0) * item.quantity); row.append(price); cartItems.append(row);
    });
    document.getElementById('merch-cart-subtotal').textContent = money(cart.reduce((total, item) => total + Number(item.price || 0) * item.quantity, 0));
  }

  document.getElementById('merch-color').addEventListener('change', updateVariant);
  document.getElementById('merch-size').addEventListener('change', () => {
    activeVariant = selectedVariant();
    document.getElementById('merch-product-price').textContent = activeVariant.price == null ? productPrice(activeProduct) : money(Number(activeVariant.price));
    setGallery(activeVariant);
  });
  document.getElementById('merch-add-to-cart').addEventListener('click', () => {
    const quantity = Math.max(1, Math.min(10, Number(document.getElementById('merch-quantity').value) || 1));
    const existing = cart.find(item => String(item.variantId) === String(activeVariant.id));
    if (existing) existing.quantity = Math.min(10, existing.quantity + quantity);
    else cart.push({variantId: activeVariant.id, productId: activeProduct.id, name: activeProduct.name, color: activeVariant.color, size: activeVariant.size, price: Number(activeVariant.price || 0), image: activeVariant.image || activeProduct.image, quantity});
    saveCart(); document.getElementById('merch-add-status').textContent = 'Added to cart.';
  });
  document.querySelectorAll('.merch-cart-trigger').forEach(button => button.addEventListener('click', () => { renderCart(); cartDialog.showModal(); }));
  document.querySelectorAll('.merch-dialog-close').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
  document.querySelectorAll('.merch-dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }));

  renderCart();
  fetch('/api/merch', {cache: 'no-store'}).then(async response => {
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Merchandise could not be loaded.');
    return data;
  }).then(data => {
    if (!data.products.length) { status.textContent = 'New Fieldhouse merchandise is coming soon.'; return; }
    data.products.forEach(product => {
      const card = template.content.firstElementChild.cloneNode(true); const image = card.querySelector('img');
      if (product.image) { image.src = product.image; image.alt = product.name; }
      else { image.remove(); card.querySelector('.merch-image').classList.add('merch-image-empty'); }
      card.querySelector('.merch-card-title').textContent = product.name;
      card.querySelector('.merch-price').textContent = productPrice(product);
      card.querySelector('.merch-card-open').addEventListener('click', () => openProduct(product)); grid.append(card);
    });
    status.textContent = `${data.products.length} style${data.products.length === 1 ? '' : 's'} available.`;
  }).catch(error => { status.textContent = error.message; });
})();
