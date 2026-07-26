// Favicon URLs for external links (issue #285).
//
// The host comes from the server (manualLinks.faviconHost) so every client
// agrees and a malformed url can't yield a broken <img>. DuckDuckGo's icon
// service is used rather than Google's because F95 itself already serves its
// external-link favicons from there, so the icons match what an admin sees on
// the source thread.
//
// Icons are decorative: every call site keeps its text label, and onError hides
// a failed image rather than leaving a broken-image glyph.
export function faviconUrl(host) {
  if (!host) return null;
  return `https://external-content.duckduckgo.com/ip3/${encodeURIComponent(host)}.ico`;
}

// Fallback host per kind, for links added before the server started returning
// _favicon_host (or when a custom link has no url yet).
const KIND_HOST = {
  steam: 'store.steampowered.com',
  gog: 'www.gog.com',
  itch: 'itch.io',
};

export function hostFor(link) {
  if (!link) return null;
  if (link._favicon_host) return link._favicon_host;
  if (link.url) {
    try { return new URL(link.url).hostname || null; } catch { /* ignore */ }
  }
  return KIND_HOST[link.kind] || null;
}
