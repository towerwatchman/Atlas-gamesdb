"""
Parse a single F95 thread page into a structured dict.

This is a pure function over HTML so it can be unit-tested against saved
fixtures without touching the network. The two guest-gating structures
documented on the Eternum pages are handled explicitly:

  1. External / download links are replaced for guests by
       <div class="messageHide messageHide--link">You must be registered ...</div>
  2. Genre / Installation / Changelog / Developer Notes / Fan Signatures are
     wrapped in <div class="bbCodeSpoiler"> blocks that for guests read
     "You don't have permission to view the spoiler content."

When logged in, both resolve to real content, which is what we extract.
"""
import re
from urllib.parse import unquote, urlparse, parse_qs

from bs4 import BeautifulSoup, NavigableString, Tag

# Hosts we treat as download mirrors (kept with their URL, grouped by OS).
DOWNLOAD_HOSTS = (
    "mega.nz", "mediafire.com", "mixdrop", "gofile.io", "pixeldrain.com",
    "workupload.com", "akirabox.com", "anonfiles", "1fichier.com",
    "racaty", "bayfiles", "uploadhaven", "dropbox.com",
)

# Top-level section headers. F95 game threads only really use these three as
# top-level dividers; words like "patch", "mod", "walkthrough", "save" are
# content TYPES that appear as sub-group labels (e.g. a "Patch" group inside
# DOWNLOAD), NOT section headers — treating them as sections mis-routes every
# link that follows. Type classification still uses those words (TYPE_RULES).
SECTION_HEADERS = {
    "download", "downloads", "extras", "extra",
    "translations", "translation",
}

# Inline "<b>Label</b>: value" fields we read directly.
INLINE_LABELS = {
    "thread updated": "thread_updated",
    "release date": "release_date",
    "developer": "developer",
    "censored": "censored",
    "version": "version",
    "os": "os",
    "language": "language",
    "length": "length",
    "voice": "voice",
}

# Spoiler-gated sections (logged-in only).
SPOILER_LABELS = {
    "genre": "genre",
    "installation": "installation",
    "changelog": "changelog",
    "developer notes": "developer_notes",
    "fan signatures": "fan_signatures",
}


def _unwrap(href):
    """Unwrap F95's proxy / link-confirmation wrappers to the real URL.

    NOTE: /masked/ links are server-side encrypted and CANNOT be decoded
    offline, so they are returned unchanged here — resolve them at request
    time with auth.F95Session.resolve_masked(). Only ?url=-style wrappers
    (which carry the real URL in a query param) are unwrapped.
    """
    if not href:
        return href
    if "link-confirmation" in href or "proxy.php" in href:
        q = parse_qs(urlparse(href).query)
        for k in ("url", "u", "link", "dest"):
            if k in q:
                return unquote(q[k][0])
    return href


def _is_masked(url):
    return "/masked/" in (url or "")


def _host_of(url):
    """Real destination host, even for masked links (/masked/<host>/...)."""
    if _is_masked(url):
        seg = url.split("/masked/", 1)[1].split("/", 1)[0]
        return seg.replace("www.", "")
    return _netloc(url)


def _classify_external(url):
    """Return (kind, value) for store/social URLs we care about, else None."""
    patterns = [
        ("steam_appid", r"store\.steampowered\.com/app/(\d+)"),
        ("steam_community", r"steamcommunity\.com/(?:app|games)/(\d+)"),
        ("itch_url", r"https?://([\w-]+\.itch\.io(?:/[\w-]+)?)"),
        ("vndb_id", r"vndb\.org/(v\d+)"),
        ("patreon", r"patreon\.com/([\w-]+)"),
        ("subscribestar", r"subscribestar\.adult/([\w-]+)"),
        ("discord", r"discord\.(?:gg|com/invite)/([\w-]+)"),
        ("gamejolt", r"gamejolt\.com/games/[\w-]+/(\d+)"),
        ("twitter", r"(?:twitter|x)\.com/([\w]+)"),
    ]
    for kind, pat in patterns:
        m = re.search(pat, url, re.I)
        if m:
            return kind, m.group(1)
    return None


def _download_host(url):
    low = url.lower()
    for host in DOWNLOAD_HOSTS:
        if host in low:
            return host
    return None


def _netloc(url):
    return urlparse(url).netloc.replace("www.", "")


def _filename_from_url(url):
    """Best-effort file/label from a URL path (strips F95's numeric prefix)."""
    tail = urlparse(url).path.rstrip("/").split("/")[-1]
    tail = re.sub(r"^\d+_", "", tail)  # attachments.f95zone.to/2021/09/1410346_Name.zip
    return unquote(tail)


# Normalised type for each download / attachment. Rules are checked top-down;
# word boundaries (\b) keep e.g. "Part 1" from matching "art".
TYPE_RULES = [
    ("translation",    [r"translation", r"\btl\b"]),
    ("walkthrough",    [r"walkthrough", r"\bwt\s?mod\b", r"\bwtmod\b"]),
    ("gallery_unlock", [r"gallery", r"unlock"]),
    ("cheat",          [r"cheat"]),
    ("soundtrack",     [r"soundtrack", r"\bost\b"]),
    ("wallpaper_art",  [r"wallpaper", r"\bbanner", r"\bart\b", r"character (?:intro|banner)"]),
    ("save",           [r"\bsaves?\b", r"save\s?(?:file|data)"]),
    ("patch",          [r"patch"]),
    ("mod",            [r"\bmods?\b"]),
    ("guide",          [r"\bguide\b", r"\bfaq\b"]),
]


def _classify_type(section, group, label, name):
    sec = (section or "").lower()
    if sec.startswith("translation"):
        return "translation"
    text = " ".join(x for x in (group, label, name) if x).lower()
    for kind, pats in TYPE_RULES:
        if any(re.search(p, text) for p in pats):
            return kind
    if sec in ("download", "downloads"):
        return "game"
    return "other"


def _inline_value(b_tag):
    """Text immediately following a '<b>Label</b>:' up to the next <br>/<b>."""
    parts = []
    for sib in b_tag.next_siblings:
        if isinstance(sib, Tag):
            if sib.name in ("b", "br", "a"):
                # next label, line break, or the start of inline links
                break
            if "messageHide" in (sib.get("class") or []):
                # guest-gated link placeholder; stop the inline value here
                break
            if sib.name == "div" and "bbCodeSpoiler" in (sib.get("class") or []):
                break
            parts.append(sib.get_text(" ", strip=True))
        else:
            parts.append(str(sib))
    text = " ".join(p for p in parts if p).strip()
    return text.lstrip(":").strip()


def _spoiler_after(b_tag):
    """The bbCodeSpoiler block following a label; None if absent.
    Returns (text, locked) where locked means guest-gated."""
    for sib in b_tag.next_siblings:
        if isinstance(sib, Tag):
            if sib.name == "b":
                return None
            if sib.name == "div" and "bbCodeSpoiler" in (sib.get("class") or []):
                txt = sib.get_text(" ", strip=True)
                locked = "permission to view the spoiler" in txt
                return ("" if locked else txt, locked)
    return None


def parse_thread_detail(html):
    soup = BeautifulSoup(html, "lxml")
    out = {
        "thread_id": None, "logged_in": None, "title": None, "prefixes": [],
        "cover_url": "", "screens": [], "rating": None, "votes": None,
        "overview": "", "tags": [],
        "external_ids": {}, "downloads": [], "extras": [], "translations": [],
        "spoilers": {},
        "locked_link_count": 0, "locked_spoiler_count": 0,
    }
    for field in INLINE_LABELS.values():
        out[field] = ""
    out["vndb"] = ""

    root = soup.find("html")
    if root is not None:
        out["logged_in"] = root.get("data-logged-in") == "true"
        m = re.search(r"thread-(\d+)", root.get("data-content-key", "") or "")
        if m:
            out["thread_id"] = m.group(1)

    # Title + prefixes from the header.
    h1 = soup.select_one("h1.p-title-value")
    if h1:
        out["prefixes"] = [s.get_text(strip=True) for s in h1.select("span.label, span[class^=pre-]")]
        # title is the trailing text node after the prefix labels
        out["title"] = h1.get_text(" ", strip=True)

    # Cover: prefer the thread cover (og:image) over the generic banner image.
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        out["cover_url"] = og["content"]

    # Rating + votes.
    stars = soup.select_one("span.ratingStars")
    if stars and stars.get("title"):
        m = re.search(r"([\d.]+)", stars["title"])
        if m:
            out["rating"] = float(m.group(1))
    votes = soup.find("span", class_="ratingStarsRow-text")
    if votes:
        m = re.search(r"([\d,]+)", votes.get_text())
        if m:
            out["votes"] = int(m.group(1).replace(",", ""))

    # Tags (full set is only present when logged in).
    out["tags"] = [a.get_text(strip=True) for a in soup.select("span.js-tagList a")]

    # ---- first post body ----
    body = soup.find("div", class_="bbWrapper")
    if body is None:
        return out

    out["locked_link_count"] = len(body.find_all("div", class_="messageHide"))
    out["locked_spoiler_count"] = len(
        [d for d in body.find_all("div", class_="bbCodeBlock-content")
         if "permission to view the spoiler" in d.get_text()]
    )

    # Labeled fields.
    for b in body.find_all("b"):
        label = b.get_text(strip=True).rstrip(":").lower()
        if label in INLINE_LABELS:
            val = _inline_value(b)
            if val:
                out[INLINE_LABELS[label]] = val
        elif label in ("vnbd", "vndb"):  # uploader frequently typos VNDB as VNBD
            # value is a link (gated); captured via external-id scan below
            pass
        elif label in SPOILER_LABELS:
            sp = _spoiler_after(b)
            if sp is not None:
                text, locked = sp
                out["spoilers"][SPOILER_LABELS[label]] = None if locked else text

    # Overview: text after the <b>Overview</b>: label, up to the first block.
    ov = body.find("b", string=re.compile(r"^\s*Overview\s*:?\s*$", re.I))
    if ov:
        parts = []
        for sib in ov.next_siblings:
            if isinstance(sib, Tag):
                if sib.name == "div" and ("bbCodeSpoiler" in (sib.get("class") or [])):
                    break
                if sib.name == "b":
                    break
                if sib.name == "br":
                    parts.append("\n")
                    continue
                parts.append(sib.get_text(" ", strip=True))
            else:
                parts.append(str(sib))
        out["overview"] = re.sub(r"\n{2,}", "\n", "".join(parts)).strip(": \n")

    # External store/social IDs first (whole-post scan).
    for a in body.find_all("a", href=True):
        cls = _classify_external(_unwrap(a["href"]))
        if cls:
            out["external_ids"].setdefault(cls[0], cls[1])

    # Downloads / extras / translations.
    #
    # The post is organised as section headers ("DOWNLOAD", "Extras",
    # "Translations", ...) each followed by <b> sub-groups ("Win/Linux",
    # "Part 1", ...) and links. Game mirrors go to `downloads`, the Extras
    # section (mods/walkthroughs/...) to `extras`, and the Translations
    # section to `translations`. Each item appears in exactly one list.
    downloads, extras, translations = [], [], []
    seen = set()
    section = ""
    group = ""
    for node in body.descendants:
        if isinstance(node, Tag) and node.name == "b":
            label = node.get_text(" ", strip=True).rstrip(":")
            low = label.lower()
            if low in SECTION_HEADERS:
                section, group = label, ""
            elif label:
                group = label
        elif isinstance(node, Tag) and node.name == "a" and node.get("href"):
            # Skip screenshot / lightbox image links — those are captured as
            # `screens`, not downloads.
            classes = node.get("class") or []
            if "js-lbImage" in classes or node.find("img"):
                continue
            url = _unwrap(node["href"])
            text = node.get_text(" ", strip=True)
            host = _download_host(url) or _host_of(url)
            sec_low = section.lower()
            is_game = sec_low in ("download", "downloads")
            in_file = bool(_download_host(url)) or "attachments.f95zone.to" in url
            in_extras = bool(section) and not is_game
            if not (in_file or in_extras):
                continue
            if url in seen:
                continue
            seen.add(url)
            label = text or _filename_from_url(url)
            # Type from the visible label first (authoritative — "Multi Mod"
            # stays a mod even though its thread slug says "walkthrough");
            # fall back to the href filename when the label is generic.
            kind = _classify_type(section, group, label, "")
            if kind == "other":
                alt = _classify_type(section, group, "", _filename_from_url(url))
                if alt != "other":
                    kind = alt
            entry = {
                "section": section,
                "group": group,
                "label": label,
                "type": kind,
                "host": host,
                "url": url,
                "masked": _is_masked(node["href"]),
            }
            if sec_low.startswith("translation"):
                translations.append(entry)
            elif is_game:
                downloads.append(entry)
            else:
                extras.append(entry)
    out["downloads"] = downloads
    out["extras"] = extras
    out["translations"] = translations

    # Screenshots: attachment images in the post (skip the generic banner).
    screens = []
    for a in body.find_all("a", href=True):
        href = a["href"]
        if "attachments.f95zone.to" in href and a.find("img"):
            if "f95zone_banner" in href:
                continue
            screens.append(href)
    out["screens"] = screens

    return out
