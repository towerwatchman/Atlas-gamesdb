"""
Parse a LewdCorner THREAD page into the fields the API listing doesn't carry.

The LC API (latest-updates.php?api=1) gives ids, titles, prefixes, view/like
counts and *thumbnail* images. Everything a game record actually needs -- the
overview, the tag list, the download links, the version and developer, and
full-size images -- only exists on the thread page. This is the LewdCorner
counterpart to f95_detail.py and is used the same way: a full scan on first
sight of a game, then again on demand.

Four things about LC markup are worth knowing before changing anything here.

1. THE OPENING POST IS NOT THE FIRST bbWrapper ON THE PAGE.
   XenForo renders the poster's signature/about block inside the user cell,
   which comes first in document order. On a real thread the first two
   `div.bbWrapper` elements were the author's signature links and project name;
   the actual post was the third. So the body is located by walking
   `article.message--post` -> `article.message-body` -> `div.bbWrapper`, never by
   taking the first match on the page.

2. THE REAL IMAGE IS IN THE ANCHOR, NOT THE <img>.
   Screenshots are marked up as:

       <a href="https://lewdcorner.com/attachments/6236382_takeru-jpg.796466/"
          class="js-lbImage">
         <img src="https://lewdcorner.com/data/attachments/793/793139-....jpg?hash=...">
       </a>

   The `<img src>` is a generated ~267px thumbnail. The full-size original is
   the anchor's href. Reading `img.src` -- the obvious thing -- silently
   collects thumbnails, which is what the API already gave us.

3. DOWNLOAD LINKS ARE MASKED.
   Hosts are wrapped as `/masked/out?t=<token>&r=<base64 referrer>`, where the
   token is JWT-shaped: `<base64url payload>.<signature>`. The payload decodes to
   `{"u": "<real url>"}`. Decoding is local (no request) and the signature is
   ignored -- we're reading a URL, not trusting a claim.

4. LC HAS NO Developer:/Version: LABELS.
   F95 threads carry an inline field list; LC threads only have `Overview:` and
   `DOWNLOAD ...` headings. Version and developer come from the trailing
   bracket groups in the title, the same fallback f95_detail uses.
"""
import base64
import binascii
import calendar
import json
import re

from bs4 import BeautifulSoup

# Reused so that a fix to the URL classifier or the lazy-embed reader benefits
# both sites. See docs/EXTERNAL_IDS.md.
from scraper.agents.f95_detail import _classify_external, _embed_url

BASE = "https://lewdcorner.com"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _abs(url):
    """Absolutise a site-relative or protocol-relative LC url."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return url


def unmask(href):
    """Resolve a LewdCorner /masked/out link to the URL it points at.

    The `t` parameter is JWT-shaped: base64url payload, '.', signature. Only the
    payload is needed and it decodes to {"u": "<real url>"}. Returns the input
    unchanged when it isn't a masked link or can't be decoded -- a link we can't
    read is still better recorded as-is than dropped.
    """
    if not href or "/masked/out" not in href:
        return href
    m = re.search(r"[?&]t=([^&]+)", href)
    if not m:
        return href
    token = m.group(1).split(".")[0]          # drop the signature segment
    token += "=" * (-len(token) % 4)          # restore stripped padding
    try:
        payload = json.loads(base64.urlsafe_b64decode(token).decode("utf-8", "replace"))
    except (binascii.Error, ValueError, TypeError):
        return href
    url = payload.get("u") if isinstance(payload, dict) else None
    return url or href


def _op_body(soup):
    """The opening post's content block. See note 1 in the module docstring."""
    post = soup.select_one("article.message--post")
    if post is None:
        return None
    return (post.select_one("article.message-body div.bbWrapper")
            or post.select_one("div.bbWrapper"))


def _brackets(title):
    """Trailing [bracket] groups of a thread title, outermost first."""
    return re.findall(r"\[([^\[\]]+)\]", title or "")


def _host(url):
    m = re.match(r"https?://([^/:]+)", url or "")
    return m.group(1).lower() if m else ""


def _clean_ws(text):
    return re.sub(r"[ \t]+", " ", (text or "")).strip()


# ---------------------------------------------------------------------------
# custom thread fields
# ---------------------------------------------------------------------------
# LewdCorner puts the structured game metadata in XenForo custom thread fields,
# rendered above the opening post as
#
#   <div class="message-fields message-fields--before">
#     <dl class="pairs pairs--customField" data-field="Developer">
#       <dt>Developer Name</dt><dd>Xlab</dd>
#     </dl>
#     ...
#
# This is the authoritative source for developer, version, language, OS, the two
# dates, and the developer's support links -- all of which the API listing omits.
# Before this was read, developer/version were being recovered from the title's
# bracket groups and the support links were missed entirely (they are NOT in the
# post body, which is why external_ids came back empty on every sample).

# data-field -> what we call it. LC's keys are inconsistently capitalised.
_FIELD_ALIASES = {
    "developer": "developer",
    "version": "version",
    "language": "language",
    "os": "os",
    "donations": "donations",
    "dategamerelease": "release_date",
    "dateversionrelease": "latest_update",
    "othergames": "other_games",
    "warning": "allow_updates",
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_lc_date(text):
    """"Jul 26, 2026" -> epoch seconds (UTC midnight). 0 when unparseable.

    Written here because scraper.utils.epoch.ConvertToUnixTime returns 0 for
    this format -- LC renders custom date fields as "Mon D, YYYY", which none of
    the existing converters handle.
    """
    if not text:
        return 0
    m = re.search(r"([A-Za-z]{3,})\s+(\d{1,2}),?\s+(\d{4})", str(text).strip())
    if not m:
        return 0
    month = _MONTHS.get(m.group(1)[:3].lower())
    if not month:
        return 0
    try:
        return int(calendar.timegm(
            (int(m.group(3)), month, int(m.group(2)), 0, 0, 0, 0, 0, 0)))
    except (ValueError, OverflowError):
        return 0


def extract_fields(soup):
    """The custom-field block as {key: {label, text, items, links}}.

    Keys are normalised via _FIELD_ALIASES; anything unrecognised is kept under
    its own lowercased data-field name rather than dropped, so a field LC adds
    later still shows up in the parsed output.
    """
    out = {}
    container = soup.select_one("div.message-fields")
    if container is None:
        return out
    for dl in container.select("dl[data-field]"):
        raw_key = (dl.get("data-field") or "").strip()
        if not raw_key:
            continue
        key = _FIELD_ALIASES.get(raw_key.lower(), raw_key.lower())
        dd = dl.select_one("dd")
        dt = dl.select_one("dt")
        if dd is None:
            continue
        items = [li.get_text(" ", strip=True) for li in dd.select("li")]
        items = [i for i in items if i]
        out[key] = {
            "label": dt.get_text(" ", strip=True) if dt is not None else raw_key,
            "text": _clean_ws(dd.get_text(" ", strip=True)),
            "items": items,
            "links": [(a.get_text(" ", strip=True), _abs(a.get("href")))
                      for a in dd.select("a[href]") if a.get("href")],
        }
    return out

# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------

def _attachment_id(url):
    """The numeric attachment id at the end of an LC attachment URL, if any.

    /attachments/6236382_takeru_cheeks_promo-jpg.796466/  ->  796466
    Used to de-duplicate: the same image can appear both as the banner and in
    the screenshot strip.
    """
    m = re.search(r"/attachments/[^/]*?\.(\d+)/?$", url or "")
    return m.group(1) if m else None


def extract_images(body):
    """(banner_url, screens) from an opening post.

    The banner is the single `div.bbImageWrapper[data-src]` LC puts at the top of
    the post. Screenshots come from the lightbox anchors, whose href is the
    full-size attachment -- NOT the thumbnail in the nested <img>. See note 2.
    """
    banner = None
    wrapper = body.select_one("div.bbImageWrapper[data-src]")
    if wrapper is not None:
        banner = _abs(wrapper.get("data-src"))
    if not banner:
        # Some posts inline the banner as a plain image rather than a wrapper.
        img = body.select_one("img.bbImage")
        if img is not None and not img.find_parent("a", class_="js-lbImage"):
            banner = _abs(_embed_url(img) or img.get("src"))

    screens = []
    seen = set()
    if banner:
        seen.add(_attachment_id(banner) or banner)

    for anchor in body.select("a.js-lbImage[href]"):
        full = _abs(anchor.get("href"))
        if not full:
            continue
        key = _attachment_id(full) or full
        if key in seen:
            continue
        seen.add(key)
        img = anchor.find("img")
        screens.append({
            "url": full,
            # Kept because it's already generated and cheap to serve in a list
            # view; the point is that `url` is the original, not this.
            "thumb": _abs(img.get("src")) if img is not None else None,
            "name": (img.get("alt") or img.get("title") or "").strip() or None
                    if img is not None else None,
        })
    return banner, screens


# ---------------------------------------------------------------------------
# downloads
# ---------------------------------------------------------------------------

# Hosts that are never a game download.
_SKIP_HOSTS = {
    "lewdcorner.com", "www.lewdcorner.com",
    "patreon.com", "www.patreon.com",
    "subscribestar.adult", "www.subscribestar.adult",
    "discord.gg", "discord.com", "www.discord.com",
    "twitter.com", "x.com", "www.x.com",
    "itch.io", "store.steampowered.com", "vndb.org",
    "ko-fi.com", "www.buymeacoffee.com", "buymeacoffee.com",
}

_PLATFORM_WORDS = [
    ("windows", ("win", "windows", "pc")),
    ("linux", ("linux",)),
    ("mac", ("mac", "macos", "osx")),
    ("android", ("android", "apk")),
]


def _platform_from(label):
    low = (label or "").lower()
    hits = [name for name, words in _PLATFORM_WORDS
            if any(re.search(rf"\b{w}\b", low) for w in words)]
    return hits


def extract_downloads(body):
    """Download links grouped under their `DOWNLOAD ...` heading.

    LC posts have no machine-readable structure here -- a bold heading followed
    by a run of host links. So the body is walked in document order and each
    link is attributed to the most recent heading seen. Anything before the
    first heading is attributed to None rather than guessed at.
    """
    out = []
    section = None
    for el in body.descendants:
        name = getattr(el, "name", None)
        if name in ("b", "strong"):
            text = _clean_ws(el.get_text(" ", strip=True))
            if text and "download" in text.lower():
                section = text.rstrip(":").strip()
            continue
        if name != "a":
            continue
        href = el.get("href")
        if not href:
            continue
        real = unmask(_abs(href))
        host = _host(real)
        if not host or host in _SKIP_HOSTS:
            continue
        if not real.startswith(("http://", "https://")):
            continue
        label = _clean_ws(el.get_text(" ", strip=True))
        out.append({
            "section": section,
            "label": label or host,
            "host": host,
            "url": real,
            "masked": "/masked/out" in href,
            "platforms": _platform_from(f"{section} {label}"),
        })
    return out


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------

def extract_overview(body):
    """Text between the `Overview:` heading and the next heading/spoiler."""
    label = None
    for tag in body.find_all(["b", "strong"]):
        if tag.get_text(" ", strip=True).lower().rstrip(":").strip() == "overview":
            label = tag
            break
    if label is None:
        return ""

    # next_elements walks INTO the label first, so its own "Overview:" text would
    # be captured and every overview began with a duplicated heading.
    inside = {id(d) for d in label.descendants}

    parts = []
    for el in label.next_elements:
        if id(el) in inside:
            continue
        name = getattr(el, "name", None)
        if name in ("b", "strong") and el is not label:
            break
        if name == "div" and "bbCodeSpoiler" in (el.get("class") or []):
            break
        if name is None:
            text = str(el)
            if text.strip():
                parts.append(text)
        elif name == "br":
            parts.append("\n")
    text = re.sub(r"\n{3,}", "\n\n", "".join(parts))
    text = _clean_ws_multiline(text).strip(": \n\u200b\u2060")
    # Some posts repeat the heading as plain text right after the bold one
    # ("<b>Overview:</b><br>Overview:<br>..."). That is in the source, not a
    # parsing artefact, but it isn't part of the description either.
    return re.sub(r"^overview\s*:?\s*", "", text, flags=re.I).strip()


def _clean_ws_multiline(text):
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in (text or "").splitlines()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def parse_lc_thread(html):
    """Parse a LewdCorner thread page. Never raises on odd markup."""
    soup = BeautifulSoup(html or "", "lxml")

    out = {
        "thread_id": "",
        "logged_in": False,
        "title": "",
        "prefixes": [],
        "version": "",
        "developer": "",
        "overview": "",
        "tags": [],
        "banner_url": None,
        "screens": [],
        "downloads": [],
        "external_ids": {},
        # From the custom-field block (see extract_fields).
        "fields": {},
        "language": "",
        "os": [],
        "release_date": 0,
        "latest_update": 0,
        "other_games": [],
        # Kept separately because the two disagree in practice -- see the note
        # where version is resolved below.
        "version_field": "",
        "version_title": "",
        "version_mismatch": False,
    }

    root = soup.find("html")
    if root is not None:
        out["logged_in"] = root.get("data-logged-in") == "true"
        m = re.match(r"thread-(\d+)", root.get("data-content-key") or "")
        if m:
            out["thread_id"] = m.group(1)

    h1 = soup.select_one("h1.p-title-value")
    if h1 is not None:
        # Prefix chips ("Ren'Py", "[HS]") are separate spans; strip them from the
        # title text so the title is just the game.
        out["prefixes"] = [s.get_text(strip=True)
                           for s in h1.select("span.label") if s.get_text(strip=True)]
        clone = BeautifulSoup(str(h1), "lxml").select_one("h1")
        # The prefix chips, and the thread-type icon. That icon is a FontAwesome
        # <i>/<svg> whose <title> reads "discussion", which get_text() happily
        # pulls in -- every title came out as "discussion Bright Past [...]".
        for junk in clone.select(
                "span.p-title-prefix, span.label, span.label-append, i, svg, title"):
            junk.decompose()
        out["title"] = _clean_ws(clone.get_text(" ", strip=True))

        # LC has no Version:/Developer: labels, so they come from the trailing
        # bracket groups: "Game [v1.006] [Kosmos Games]".
        groups = _brackets(out["title"])
        if groups:
            out["developer"] = groups[-1].strip()
        for group in groups:
            g = group.strip()
            if re.match(r"^(v|ver|version)?\s*\d", g, re.I) or g.lower() in (
                    "demo", "final", "completed"):
                out["version_title"] = g
                break

    out["tags"] = [a.get_text(strip=True) for a in soup.select("span.js-tagList a")
                   if a.get_text(strip=True)]

    # --- the custom-field block: the real source for most of this ----------
    fields = extract_fields(soup)
    out["fields"] = fields

    if fields.get("developer", {}).get("text"):
        out["developer"] = fields["developer"]["text"]
    out["version_field"] = fields.get("version", {}).get("text", "")

    # Version comes from the field, which is what LC treats as structured data.
    #
    # Be aware the two sources DO diverge: on the Eternum fixture the field says
    # "0.9.0" while the title says "v0.9.5 Public", because posters update the
    # title on every release and sometimes forget the field. Both are kept and a
    # mismatch is flagged rather than silently resolved, so this can be flipped
    # to prefer the title without re-deriving anything.
    out["version"] = out["version_field"] or out["version_title"]
    out["version_mismatch"] = bool(
        out["version_field"] and out["version_title"]
        and out["version_field"].lstrip("vV").strip()
        not in out["version_title"].lstrip("vV").strip())

    if fields.get("language", {}).get("text"):
        # NOTE: LC truncates long lists in the stored value itself, e.g.
        # "English, French, Italian, German, Spanish, +6". The missing entries
        # are not anywhere else on the page, so this is as complete as it gets.
        out["language"] = fields["language"]["text"]
    if fields.get("os"):
        os_field = fields["os"]
        out["os"] = os_field["items"] or (
            [os_field["text"]] if os_field["text"] else [])
    out["release_date"] = parse_lc_date(fields.get("release_date", {}).get("text"))
    out["latest_update"] = parse_lc_date(fields.get("latest_update", {}).get("text"))
    out["other_games"] = [
        {"title": title, "url": url}
        for title, url in fields.get("other_games", {}).get("links", []) if url
    ]

    # The developer's own links live in this field, NOT in the post body -- which
    # is why external_ids came back empty from body-only parsing. Read first so
    # the structured source wins over anything incidental in the post.
    for _label, href in fields.get("donations", {}).get("links", []):
        found = _classify_external(unmask(href))
        if found:
            out["external_ids"].setdefault(found[0], found[1])

    body = _op_body(soup)
    if body is None:
        return out

    out["overview"] = extract_overview(body)
    out["banner_url"], out["screens"] = extract_images(body)
    out["downloads"] = extract_downloads(body)

    # Support/social ids. Anchors first, then lazy media embeds -- same ordering
    # and the same classifier as f95_detail, so an explicit link wins.
    for anchor in body.select("a[href]"):
        found = _classify_external(unmask(_abs(anchor.get("href"))))
        if found:
            out["external_ids"].setdefault(found[0], found[1])
    for frame in body.select("iframe, [data-s9e-mediaembed-src]"):
        found = _classify_external(_embed_url(frame))
        if found:
            out["external_ids"].setdefault(found[0], found[1])

    return out
