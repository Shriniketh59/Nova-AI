// Double-submit CSRF helper.
//
// The server issues a non-httponly `csrf_token` cookie alongside the
// httponly session cookie (see server/app/routes/auth.py). Cross-site
// attackers can make the browser send cookies automatically, but they can't
// read this cookie's value (blocked by browser same-origin policy), so
// echoing it back as a header proves the request came from our own frontend.

const CSRF_COOKIE_NAME = 'csrf_token';

export function getCsrfToken() {
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${CSRF_COOKIE_NAME}=([^;]*)`)
  );
  return match ? decodeURIComponent(match[1]) : null;
}

// Returns headers with X-CSRF-Token attached when a token cookie exists.
// Safe to spread into any fetch() headers object; a no-op before login.
export function csrfHeaders(extra = {}) {
  const token = getCsrfToken();
  return token ? { ...extra, 'X-CSRF-Token': token } : extra;
}
