// ---------------------------------------------------------------------------
// Atlas search (issue #287).
//
// What was wrong: one `%term%` LIKE OR'd across four columns, then
// `ORDER BY a.atlas_id`. Three separate problems came out of that —
//
//   1. A single substring matched anywhere in title, creator, developer or
//      id_name, so "dik" also returned every game by a developer whose name
//      contains "dik", plus anything with "dik" mid-word.
//   2. Multi-word queries were treated as one literal string, so
//      "being dik" found nothing while "dik" found far too much.
//   3. Results came back in atlas_id order, so the thing you searched for was
//      wherever it happened to fall — usually not near the top.
//
// What it does now:
//   * splits the query into terms; EVERY term has to match SOMETHING
//     (AND across terms, OR across fields), which is what actually narrows it
//   * scores each row and orders by that score, so exact and prefix title
//     matches come first
//   * treats a purely numeric query as an id lookup too, across atlas_id,
//     f95_id and lc_id — pasting an id is the single most common admin search
//   * escapes LIKE wildcards, so a title containing "100%" is searchable and a
//     query of "%" no longer matches the entire table
//
// Both the row query and the COUNT query are built from the same fragment here,
// so they can't drift apart (the old code hand-wrote the count against `atlas`
// alone, which would silently mismatch the moment the WHERE touched a join).
// ---------------------------------------------------------------------------

// '!' rather than backslash as the LIKE escape character: backslash handling
// depends on the NO_BACKSLASH_ESCAPES sql_mode, '!' never does.
const ESC = '!';

/** Escape %, _ and the escape char itself for use inside a LIKE pattern. */
export function escapeLike(value) {
  return String(value ?? '').replace(/[!%_]/g, (c) => ESC + c);
}

// Columns a term can match, in rough order of how much we trust them.
const TERM_FIELDS = [
  'a.title', 'a.original_name', 'a.creator', 'a.developer', 'a.id_name',
];

const MAX_TERMS = 8;

/**
 * Build the shared FROM + WHERE + ORDER BY fragments for an atlas search.
 *
 * Returns { joinSql, whereSql, orderSql, params, countParams, terms, idQuery }.
 * `params` covers score + where placeholders (row query); `countParams` covers
 * only the where placeholders.
 */
export function buildAtlasSearch({ search = '', edited } = {}) {
  const raw = String(search ?? '').trim();
  const terms = raw ? raw.split(/\s+/).filter(Boolean).slice(0, MAX_TERMS) : [];
  const idQuery = /^\d+$/.test(raw) ? Number(raw) : null;

  const where = [];
  const whereParams = [];

  if (terms.length) {
    for (const term of terms) {
      const like = `%${escapeLike(term)}%`;
      const ors = TERM_FIELDS.map((f) => `${f} LIKE ? ESCAPE '${ESC}'`);
      const params = TERM_FIELDS.map(() => like);

      // A bare number should also find the row by id, rather than only by
      // digits appearing inside a title.
      if (/^\d+$/.test(term)) {
        ors.push('a.atlas_id = ?', 'f.f95_id = ?', 'l.lc_id = ?');
        const n = Number(term);
        params.push(n, n, n);
      }
      where.push(`(${ors.join(' OR ')})`);
      whereParams.push(...params);
    }
  }

  if (edited === '0' || edited === '1' || edited === 0 || edited === 1) {
    where.push('a.edited = ?');
    whereParams.push(Number(edited));
  }

  // --- relevance -----------------------------------------------------------
  // Scored on the whole query string, not per term: "being a dik" should rank
  // the game whose title IS that above one that merely contains all three
  // words somewhere.
  let scoreSql = '0';
  const scoreParams = [];
  if (raw) {
    const lower = raw.toLowerCase();
    const esc = escapeLike(lower);
    const parts = [];

    // exact title
    parts.push("CASE WHEN LOWER(a.title) = ? THEN 1000 ELSE 0 END");
    scoreParams.push(lower);
    // title starts with the query
    parts.push(`CASE WHEN LOWER(a.title) LIKE ? ESCAPE '${ESC}' THEN 400 ELSE 0 END`);
    scoreParams.push(`${esc}%`);
    // title contains the query
    parts.push(`CASE WHEN LOWER(a.title) LIKE ? ESCAPE '${ESC}' THEN 200 ELSE 0 END`);
    scoreParams.push(`%${esc}%`);
    // identity key (how the scraper matches) contains it
    parts.push(`CASE WHEN LOWER(a.id_name) LIKE ? ESCAPE '${ESC}' THEN 120 ELSE 0 END`);
    scoreParams.push(`%${esc}%`);
    // creator / developer
    parts.push(`CASE WHEN LOWER(a.creator) LIKE ? ESCAPE '${ESC}' THEN 80 ELSE 0 END`);
    scoreParams.push(`%${esc}%`);
    parts.push(`CASE WHEN LOWER(a.developer) LIKE ? ESCAPE '${ESC}' THEN 60 ELSE 0 END`);
    scoreParams.push(`%${esc}%`);
    // shorter titles beat longer ones at equal score, so "Eternum" outranks
    // "Eternum Fan Remake Extended" for the query "eternum"
    parts.push('GREATEST(0, 40 - CHAR_LENGTH(a.title) DIV 4)');

    if (idQuery !== null) {
      parts.push('CASE WHEN a.atlas_id = ? THEN 2000 ELSE 0 END');
      scoreParams.push(idQuery);
      // MAX(...) because the row query groups by a.atlas_id: a game may have
      // several source rows (migration 002 dropped the UNIQUE on atlas_id), so
      // this has to collapse to "did ANY of them match".
      parts.push('MAX(CASE WHEN f.f95_id = ? OR l.lc_id = ? THEN 1500 ELSE 0 END)');
      scoreParams.push(idQuery, idQuery);
    }
    scoreSql = parts.join(' + ');
  }

  // The joins are part of the shared fragment because the WHERE can reference
  // f95_id / lc_id, so the COUNT has to join them too.
  const joinSql = `
       FROM atlas a
       LEFT JOIN f95_zone f ON f.atlas_id = a.atlas_id
       LEFT JOIN lewdcorner l ON l.atlas_id = a.atlas_id`;

  const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const orderSql = raw
    ? 'ORDER BY _score DESC, a.title ASC, a.atlas_id ASC'
    : 'ORDER BY a.atlas_id';

  return {
    joinSql,
    whereSql,
    orderSql,
    scoreSql,
    params: [...scoreParams, ...whereParams],
    countParams: whereParams,
    terms,
    idQuery,
  };
}
