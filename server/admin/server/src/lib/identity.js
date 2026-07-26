// ---------------------------------------------------------------------------
// atlas identity keys: short_name and id_name.
//
// These are NOT cosmetic. `id_name` is the cross-source match key the scraper
// uses to decide whether an incoming F95 / LewdCorner / DLsite game is the one
// already in `atlas`. If a human adds a game here and we compute id_name
// differently from the scraper, the next crawl will not recognise it and will
// insert a SECOND atlas row for the same game.
//
// So this is a deliberate port of scraper/utils/parser.ParseThreadItem, as
// mirrored in scraper/agents/lewdcorner.py::_normalise_id_name:
//
//     short = re.sub(r"[\W_]+", "", (title or "").strip().replace(" ", "")).upper()
//     id_name = short + "_" + (creator or "").upper()
//
// One subtlety worth not "simplifying": Python's `\W` on a str is
// Unicode-aware, so an accented letter is a WORD character and survives the
// strip ("Café" -> "CAFÉ"). JavaScript's `\W` is ASCII-only and would delete
// it ("CAF"), which would silently produce a different key for any non-ASCII
// title. Hence the Unicode property escapes and the /u flag below.
// ---------------------------------------------------------------------------

/** Strip to letters and digits, uppercase. Mirrors Python's re.sub(r"[\W_]+"). */
export function shortName(title) {
  return String(title ?? '')
    .trim()
    .replace(/ /g, '')
    // \p{L} letters, \p{N} numbers. Everything else (including "_", which
    // Python's pattern removes explicitly) goes.
    .replace(/[^\p{L}\p{N}]+/gu, '')
    .toUpperCase();
}

/** id_name = short_name + "_" + CREATOR. */
export function idName(title, creator) {
  return `${shortName(title)}_${String(creator ?? '').toUpperCase()}`;
}

export function computeIdentity(title, creator) {
  const short = shortName(title);
  return { short_name: short, id_name: `${short}_${String(creator ?? '').toUpperCase()}` };
}
