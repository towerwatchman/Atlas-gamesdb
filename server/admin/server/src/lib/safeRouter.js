// Wraps an Express Router so that any async handler which throws or rejects is
// forwarded to Express's error-handling middleware instead of becoming an
// unhandled promise rejection (which, in Express 4, crashes the process).
//
// We monkey-patch the router's verb methods to wrap each handler in a
// try/catch-through-Promise. This keeps every route file clean (no need to
// remember a wrapper at each call site) while guaranteeing a DB error becomes
// a 500 response, not a fatal crash.
const VERBS = ['get', 'post', 'put', 'patch', 'delete', 'all'];

function wrapHandler(fn) {
  if (typeof fn !== 'function' || fn.length === 4) return fn; // skip error mw
  return function wrapped(req, res, next) {
    try {
      const out = fn(req, res, next);
      if (out && typeof out.catch === 'function') out.catch(next);
    } catch (err) {
      next(err);
    }
  };
}

export function safeRouter(router) {
  for (const verb of VERBS) {
    const original = router[verb].bind(router);
    router[verb] = (path, ...handlers) =>
      original(path, ...handlers.map(wrapHandler));
  }
  return router;
}
