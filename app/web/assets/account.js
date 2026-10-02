(() => {
  const $ = id => document.getElementById(id);
  let refreshPromise = null;
  const headers = {'Content-Type': 'application/json', 'X-Fieldhouse-Request': '1'};
  async function authFetch(url, options = {}) {
    let response = await fetch(url, {...options, headers: {...headers, ...options.headers}, credentials: 'same-origin', cache: 'no-store'});
    if (response.status === 401 && !url.startsWith('/api/auth/login') && !url.startsWith('/api/auth/signup')) {
      if (!refreshPromise) refreshPromise = fetch('/api/auth/refresh', {method: 'POST', headers, credentials: 'same-origin', cache: 'no-store'}).finally(() => { refreshPromise = null; });
      const refresh = await refreshPromise;
      if (refresh.ok) response = await fetch(url, {...options, headers: {...headers, ...options.headers}, credentials: 'same-origin', cache: 'no-store'});
    }
    return response;
  }
  async function signOut() {
    const response = await fetch('/api/auth/logout', {method:'POST',headers,credentials:'same-origin'});
    if (!response.ok) throw new Error('Could not sign out. Please try again.');
    location.assign('/account');
  }
  window.fieldhouseAuth = {fetch: authFetch, signOut};
  const menu = $('profile-dropdown');
  document.addEventListener('click', event => { if (menu && !menu.contains(event.target)) menu.open = false; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && menu?.open) { menu.open = false; menu.querySelector('summary').focus(); } });
  document.querySelectorAll('[data-account-signout]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try { await signOut(); } catch (error) { $('profile-status').textContent = error.message; button.disabled = false; }
  }));
  async function loadAccount() {
    try {
      const response = await authFetch('/api/auth/me');
      if (response.status === 401) {
        $('profile-guest').hidden = false;
        if ($('account-forms')) $('account-forms').hidden = false;
        return;
      }
      if (!response.ok) throw new Error('Account details could not be loaded. Please refresh to try again.');
      const user = await response.json();
      $('profile-guest').hidden = true;
      $('profile-member').hidden = false;
      $('profile-name').textContent = user.name || 'My account';
      $('profile-email').textContent = user.email;
      // Create the admin link only for a server-verified administrator.
      if (user.is_admin) {
        const link = document.createElement('a'); link.href = '/admin/bookings'; link.textContent = 'Booking Admin';
        $('profile-admin').replaceChildren(link);
      }
      if ($('account-forms')) {
        $('account-forms').hidden = true;
        $('account-summary').hidden = false;
        $('account-email').textContent = user.email;
        $('account-role').textContent = user.is_admin ? 'Administrator' : 'Member';
        if (user.is_admin && new URLSearchParams(location.search).get('next') === 'admin') location.replace('/admin/bookings');
        else if (!user.is_admin && new URLSearchParams(location.search).get('next') === 'admin') $('account-status').textContent = 'This account does not have admin permission.';
      }
    } catch (error) {
      $('profile-status').textContent = error.message;
      if ($('account-forms')) $('account-forms').hidden = false;
    }
  }
  document.querySelectorAll('[data-auth-mode]').forEach(button => button.addEventListener('click', () => {
    const signup = button.dataset.authMode === 'signup';
    $('signup-form').hidden = !signup; $('login-form').hidden = signup;
    document.querySelectorAll('[data-auth-mode]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    $('account-status').textContent = '';
  }));
  ['login','signup'].forEach(action => {
    const form = $(`${action}-form`);
    if (!form) return;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const button = form.querySelector('button[type=submit]'); button.disabled = true;
      $('account-status').textContent = action === 'login' ? 'Signing in…' : 'Creating your account…';
      try {
        const response = await fetch(`/api/auth/${action}`, {method:'POST',headers,credentials:'same-origin',body:JSON.stringify(Object.fromEntries(new FormData(form)))});
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check your account details.');
        form.querySelector('[name=password]').value = '';
        $('account-status').textContent = data.message || 'You’re signed in.';
        if (data.signed_in) await loadAccount();
      } catch (error) { $('account-status').textContent = error.message || 'Please try again.'; }
      finally { button.disabled = false; }
    });
  });
  // Confirmation links may include provider session fragments. Use normal sign-in
  // after confirmation and remove those credentials from the visible URL.
  if (location.pathname === '/account' && location.hash.includes('access_token=')) {
    history.replaceState(null, '', location.pathname + location.search);
    $('account-status').textContent = 'Your email is confirmed. Sign in to continue.';
  }
  loadAccount();
})();
