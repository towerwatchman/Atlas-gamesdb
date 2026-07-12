// Thin fetch wrapper. Cookies carry the session, so every call is
// credentials:'include'. Non-2xx throws an Error with the server's message.
//
// Admin API lives under /admin/api on the server. Callers pass paths like
// "/api/atlas"; we rewrite the leading "/api" to "/admin/api" so the UI code
// stays clean and the public "/api/updates" feed is never touched here.
function toAdminApi(url) {
  if (url.startsWith('/api/')) return '/admin' + url;
  return url;
}

async function req(method, url, body) {
  const opts = { method, credentials: 'include', headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(toAdminApi(url), opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}

export const api = {
  get: (u) => req('GET', u),
  post: (u, b) => req('POST', u, b),
  patch: (u, b) => req('PATCH', u, b),
  del: (u) => req('DELETE', u),
};

export const fmtTime = (epoch) =>
  epoch ? new Date(epoch * 1000).toLocaleString() : '—';
