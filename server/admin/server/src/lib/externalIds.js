// ---------------------------------------------------------------------------
// Render the scraper's `atlas.external_ids` JSON as displayable links.
//
// That column holds ids the scraper extracted from the source thread, e.g.
//
//   {"patreon": "onceinalifetime", "subscribestar": "caribdis",
//    "itch_url": "caribdis.itch.io", "discord": "caribdisgames",
//    "twitter": "Caribdis_games", "vndb_id": "v31929"}
//
// It was never surfaced in the admin UI: it isn't in EDITABLE_ATLAS_COLUMNS and
// nothing read it, so a game with a rich external_ids blob and no admin-added
// links showed an empty External links section.
//
// These are READ-ONLY on purpose. The scraper rewrites the whole column on
// every refresh, so anything typed here would be silently discarded on the next
// crawl. Admin-owned links belong in atlas_manual_links, which the scraper never
// touches.
//
// This is the inverse of scraper/agents/f95_detail.py::_classify_external —
// that turns a URL into (kind, id), this turns (kind, id) back into a URL. If a
// pattern is added there, add the matching entry here.
// ---------------------------------------------------------------------------

const numeric = (v) => /^\d+$/.test(String(v));

export const EXTERNAL_ID_KINDS = {
  steam_appid: {
    label: 'Steam',
    host: 'store.steampowered.com',
    url: (v) => `https://store.steampowered.com/app/${encodeURIComponent(v)}/`,
  },
  steam_community: {
    label: 'Steam community',
    host: 'steamcommunity.com',
    url: (v) => `https://steamcommunity.com/app/${encodeURIComponent(v)}`,
  },
  itch_url: {
    label: 'itch.io',
    // Stored as a bare host (+ optional path), e.g. "caribdis.itch.io".
    host: (v) => String(v).split('/')[0],
    url: (v) => `https://${v}`,
  },
  gog_url: {
    label: 'GOG',
    host: 'www.gog.com',
    url: (v) => `https://www.gog.com/game/${encodeURIComponent(v)}`,
  },
  vndb_id: {
    label: 'VNDB',
    host: 'vndb.org',
    url: (v) => `https://vndb.org/${encodeURIComponent(v)}`,
  },
  patreon: {
    label: 'Patreon',
    host: 'www.patreon.com',
    // An all-digits value came from the old /user?u=<id> form and has no slug;
    // anything else is a creator slug, which now lives under /c/.
    url: (v) => (numeric(v)
      ? `https://www.patreon.com/user?u=${encodeURIComponent(v)}`
      : `https://www.patreon.com/c/${encodeURIComponent(v)}`),
  },
  subscribestar: {
    label: 'SubscribeStar',
    host: 'subscribestar.adult',
    url: (v) => `https://subscribestar.adult/${encodeURIComponent(v)}`,
  },
  buymeacoffee: {
    label: 'Buy Me a Coffee',
    host: 'www.buymeacoffee.com',
    url: (v) => `https://www.buymeacoffee.com/${encodeURIComponent(v)}`,
  },
  kofi: {
    label: 'Ko-fi',
    host: 'ko-fi.com',
    url: (v) => `https://ko-fi.com/${encodeURIComponent(v)}`,
  },
  discord: {
    label: 'Discord',
    host: 'discord.com',
    url: (v) => `https://discord.gg/${encodeURIComponent(v)}`,
  },
  twitter: {
    label: 'X / Twitter',
    host: 'x.com',
    url: (v) => `https://x.com/${encodeURIComponent(v)}`,
  },
  bluesky: {
    label: 'Bluesky',
    host: 'bsky.app',
    url: (v) => `https://bsky.app/profile/${encodeURIComponent(v)}`,
  },
  facebook: {
    label: 'Facebook',
    host: 'www.facebook.com',
    url: (v) => (numeric(v)
      ? `https://www.facebook.com/profile.php?id=${encodeURIComponent(v)}`
      : `https://www.facebook.com/${encodeURIComponent(v)}`),
  },
  gamejolt: {
    label: 'Game Jolt',
    host: 'gamejolt.com',
    // Only the numeric id is stored and the public URL needs the slug too, so
    // there's nothing safe to link to. Shown as a value without a link.
    url: () => null,
  },
};

/**
 * Turn the stored external_ids blob into display rows.
 *
 * Tolerant by design: the column is free-form JSON written by the scraper, so a
 * malformed blob, a null, an unknown key or a non-string value must degrade to
 * "show what we have" rather than break the edit modal.
 */
export function parseExternalIds(raw) {
  if (!raw) return [];
  let obj = raw;
  if (typeof raw === 'string') {
    try {
      obj = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return [];

  const out = [];
  for (const [key, value] of Object.entries(obj)) {
    if (value === null || value === undefined || value === '') continue;
    // A value can legitimately be a list (several ids for one platform).
    const values = Array.isArray(value) ? value : [value];
    for (const v of values) {
      if (v === null || v === undefined || v === '') continue;
      const spec = EXTERNAL_ID_KINDS[key];
      const text = String(v);
      let url = null;
      if (spec && typeof spec.url === 'function') {
        try { url = spec.url(text); } catch { url = null; }
      }
      let host = null;
      if (spec) host = typeof spec.host === 'function' ? spec.host(text) : spec.host;
      out.push({
        key,
        label: spec ? spec.label : key,
        value: text,
        url,
        favicon_host: host || null,
        // Flagged so the UI can say why these can't be edited here.
        source: 'scraper',
        known: Boolean(spec),
      });
    }
  }
  // Known platforms first, then alphabetical, so the list is stable between
  // loads rather than following JSON key order.
  return out.sort((a, b) => (Number(b.known) - Number(a.known))
    || a.label.localeCompare(b.label));
}
