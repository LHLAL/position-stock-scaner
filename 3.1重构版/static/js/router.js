// router.js · v1.0 · 2026-06-15
// Hash-based SPA router

const DEFAULT_ROUTE = '#/v2';

let _routes = {};
let _currentRoute = null;

// ── Public API ────────────────────────────────────────────

/**
 * Initialize router with route map.
 * @param {Object} routes - { '#/v2': initFn, '#/scan': initFn, ... }
 */
export function initRouter(routes) {
  _routes = routes;

  // Listen for hash changes
  window.addEventListener('hashchange', _onHashChange);

  // Navigate to initial route
  const initialHash = window.location.hash || DEFAULT_ROUTE;
  _navigateTo(initialHash);
}

/**
 * Navigate to a hash route.
 * @param {string} hash - e.g. '#/scan'
 */
export function navigate(hash) {
  if (!hash.startsWith('#')) hash = '#' + hash;
  // If hash unchanged, still trigger navigation (force re-init)
  if (hash === window.location.hash) {
    _navigateTo(hash);
  } else {
    window.location.hash = hash;
  }
}

/**
 * Get current active route.
 * @returns {string} current hash like '#/v2'
 */
export function getCurrentRoute() {
  return _currentRoute;
}

// ── Internal ──────────────────────────────────────────────

function _onHashChange() {
  // Strip query string from hash (e.g. "#/scan?t=123" → "#/scan")
  const raw = window.location.hash.split('?')[0] || DEFAULT_ROUTE;
  _navigateTo(raw);
}

function _navigateTo(hash) {
  // Guard: don't re-init same route
  if (hash === _currentRoute) return;

  // Activate matching route or default
  let targetHash = hash;
  if (!_routes[targetHash]) {
    targetHash = DEFAULT_ROUTE;
    window.location.hash = targetHash;
  }

  // Hide current view (before switching)
  if (_currentRoute) {
    const currentViewId = _currentRoute.replace('#/', '');
    const currentEl = document.getElementById(`view-${currentViewId}`);
    if (currentEl) {
      currentEl.classList.add('view-hidden');
      currentEl.classList.remove('view-active');
    }
  }

  // Show target view
  const viewId = targetHash.replace('#/', '');
  const activeEl = document.getElementById(`view-${viewId}`);
  if (activeEl) {
    activeEl.classList.remove('view-hidden');
    activeEl.classList.add('view-active');
  }

  // Call the route's init function
  if (_routes[targetHash]) {
    _routes[targetHash]();
  }

  _currentRoute = targetHash;

  // Update nav active state
  _updateNavActive(targetHash);
}

function _updateNavActive(activeHash) {
  document.querySelectorAll('[data-route]').forEach(link => {
    const isActive = link.dataset.route === activeHash;
    link.classList.toggle('active', isActive);
  });
}