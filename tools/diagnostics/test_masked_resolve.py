#!/usr/bin/env python3
"""Test whether F95 /masked/ links can be resolved without user interaction.

This answers the single question the client-side download feature rests on:
when an authenticated session requests a masked link minted for THAT session,
does F95 hand back the destination, or does it require a human?

Four outcomes, each implying a different client:

  A. 3xx + Location pointing off-site
     Fully automatable. Resolve in the background, no window needed.

  B. 200 and .host_link is present in the STATIC html
     Automatable. Read the href straight out of the response, no browser.

  D. 200, no .host_link, and no challenge widget
     The link is injected by JavaScript. requests cannot see it, but a real
     browser will. An Electron window resolves this with no user interaction,
     and the auto-click is pure convenience. This is what the Tampermonkey
     MutationObserver implies: you only need to watch for mutations if the
     element arrives after load.

  C. 200 with an actual challenge widget
     A human has to clear it. Visible browser window, throughput is capped,
     and caching resolved urls matters.

Telling D apart from C is the point of this revision. The previous version
substring-matched the word "captcha" anywhere in the body, which is a bad
test: it hits css class names, comments and prose just as happily as a real
widget. It reported C for a 3.2KB page that shows no sign of carrying one.

Usage:
    python tools/diagnostics/test_masked_resolve.py 295876
    python tools/diagnostics/test_masked_resolve.py 295876 --save-body
    python tools/diagnostics/test_masked_resolve.py 295876 --dry-run

Credentials come from the same config the scraper uses. Nothing is written
to the database.
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from scraper import auth  # noqa: E402
from scraper.config import config  # noqa: E402
from scraper.agents.f95_detail import parse_thread_detail  # noqa: E402

THREAD_URL = "https://f95zone.to/threads/{f95_id}/"

# XenForo marks off-site links with this class.
EXTERNAL_HREF = re.compile(r'href="(https?://[^"]+)"[^>]*link--external')
# The element the Tampermonkey script and F95Checker both click.
HOST_LINK = re.compile(r'\bhost_link\b')
HOST_LINK_HREF = re.compile(
    r'<a[^>]*\bhost_link\b[^>]*href="([^"]+)"'
    r'|<a[^>]*href="([^"]+)"[^>]*\bhost_link\b'
)
SCRIPT_SRC = re.compile(r'<script[^>]+src="([^"]+)"', re.I)
INLINE_SCRIPT = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.I | re.S)

# Hosts that serve real challenge widgets. A script tag pointing at one of
# these is strong evidence a human is required.
CHALLENGE_SCRIPT_HOSTS = (
    "challenges.cloudflare.com",
    "hcaptcha.com",
    "recaptcha.net",
    "gstatic.com/recaptcha",
    "google.com/recaptcha",
    "captcha-delivery.com",
    "arkoselabs.com",
    "funcaptcha.com",
)

# Markup a challenge widget mounts into. Also strong evidence.
CHALLENGE_MARKUP = (
    ("cf-turnstile", "Cloudflare Turnstile widget"),
    ("g-recaptcha", "Google reCAPTCHA widget"),
    ("h-captcha", "hCaptcha widget"),
    ("challenge-form", "Cloudflare challenge form"),
    ("__cf_chl", "Cloudflare challenge token"),
    ("cf_chl_", "Cloudflare challenge token"),
    ("data-sitekey", "captcha site key attribute"),
)

# Dump bodies smaller than this in full. 1500 chars was not enough to see
# past an inline logo svg.
FULL_DUMP_LIMIT = 40_000


def _short(url, width=110):
    url = url or ""
    return url if len(url) <= width else url[: width - 3] + "..."


def describe_link(index, link):
    return (
        f"  [{index:>2}] {link.get('host', '?'):<18} "
        f"group={link.get('group', '') or '(none)':<10} "
        f"label={link.get('label', '') or '(none)':<14} "
        f"masked={str(link.get('masked', False)):<5} "
        f"{_short(link.get('url', ''), 70)}"
    )


def user_id_from_masked(url):
    """Second numeric segment of /masked/<host>/<thread>/<user>/..."""
    if "/masked/" not in (url or ""):
        return None
    parts = url.split("/masked/", 1)[1].split("/")
    return parts[2] if len(parts) > 2 else None


def find_word_context(body, word="captcha", width=90, limit=6):
    """Every occurrence of a word, with surrounding text.

    The old detector fired on this word alone. Showing context makes it
    obvious whether it is a real challenge or just a class name or comment.
    """
    hits = []
    lowered = body.lower()
    start = 0
    while len(hits) < limit:
        found = lowered.find(word, start)
        if found == -1:
            break
        left = max(0, found - width // 2)
        right = min(len(body), found + width // 2)
        snippet = body[left:right].replace("\n", " ").replace("\r", "")
        hits.append(re.sub(r"\s+", " ", snippet).strip())
        start = found + 1
    return hits


def analyse_body(body):
    """Classify a 200 response. Returns the evidence, not just a verdict."""
    scripts = SCRIPT_SRC.findall(body)
    inline = INLINE_SCRIPT.findall(body)
    lowered = body.lower()

    signals = []
    for src in scripts:
        for host in CHALLENGE_SCRIPT_HOSTS:
            if host in src.lower():
                signals.append((f"script from {host}", src))
    for needle, label in CHALLENGE_MARKUP:
        if needle.lower() in lowered:
            signals.append((label, needle))

    href_match = HOST_LINK_HREF.search(body)
    host_link_href = None
    if href_match:
        host_link_href = href_match.group(1) or href_match.group(2)

    return {
        "scripts": scripts,
        "inline_script_count": len(inline),
        "inline_script_chars": sum(len(script) for script in inline),
        "challenge_signals": signals,
        "host_link_present": bool(HOST_LINK.search(body)),
        "host_link_href": host_link_href,
        "captcha_word_hits": find_word_context(body),
        "length": len(body),
    }


def probe_masked(session, url, save_body=None, show_body=True):
    """Request a masked link and classify what came back."""
    print(f"\n  Requesting: {_short(url)}")

    response = session.session.get(url, timeout=30, allow_redirects=False)
    location = response.headers.get("Location")
    print(f"  Status: {response.status_code}")
    if location:
        print(f"  Location: {_short(location)}")

    if response.status_code in (301, 302, 303, 307, 308) and location:
        if "/masked/" not in location:
            return {
                "outcome": "A",
                "destination": location,
                "host": urlparse(location).netloc,
                "has_fragment": "#" in location,
            }
        print("  Redirect stayed inside /masked/ - following it.")

    response = session.session.get(url, timeout=30, allow_redirects=True)
    final_host = urlparse(response.url).netloc
    print(f"  Final URL: {_short(response.url)}")

    if "f95zone.to" not in final_host:
        return {
            "outcome": "A",
            "destination": response.url,
            "host": final_host,
            "has_fragment": "#" in response.url,
        }

    body = response.text or ""
    info = analyse_body(body)

    if save_body:
        with open(save_body, "w", encoding="utf-8") as handle:
            handle.write(body)
        print(f"  Body written to {save_body}")

    print(f"\n  Body length: {info['length']} bytes")
    print(f"  External scripts: {len(info['scripts'])}")
    for src in info["scripts"]:
        print(f"    - {_short(src, 90)}")
    print(f"  Inline scripts: {info['inline_script_count']} "
          f"({info['inline_script_chars']} chars)")
    print(f"  .host_link in static html: {info['host_link_present']}")
    if info["host_link_href"]:
        print(f"    href: {_short(info['host_link_href'])}")

    if info["captcha_word_hits"]:
        print(f"\n  Occurrences of 'captcha' ({len(info['captcha_word_hits'])}):")
        for hit in info["captcha_word_hits"]:
            print(f"    ...{hit}...")

    if info["challenge_signals"]:
        print("\n  Challenge signals:")
        for label, evidence in info["challenge_signals"]:
            print(f"    ! {label}  ({_short(evidence, 60)})")
    else:
        print("\n  No challenge widget detected.")

    if show_body and info["length"] <= FULL_DUMP_LIMIT:
        print(f"\n  --- full body ({info['length']} bytes) ---")
        print(body)
        print("  --- end ---")

    # A link already in the markup means no browser is needed at all.
    external = EXTERNAL_HREF.search(body)
    if info["host_link_href"] or external:
        return {
            "outcome": "B",
            "destination": info["host_link_href"] or external.group(1),
            "info": info,
        }
    if info["challenge_signals"]:
        return {"outcome": "C", "info": info}
    # No link, no challenge: the markup is built client-side.
    return {"outcome": "D", "info": info}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("f95_id", help="F95 thread id, e.g. 295876")
    parser.add_argument("--index", type=int, default=0,
                        help="which masked link to resolve (default: first)")
    parser.add_argument("--all", action="store_true",
                        help="resolve every masked link (slow)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list links only, resolve nothing")
    parser.add_argument("--save-body", action="store_true",
                        help="write the response body to a file")
    parser.add_argument("--no-body", action="store_true",
                        help="skip printing the body")
    parser.add_argument("--json", action="store_true",
                        help="emit parsed links as JSON and exit")
    args = parser.parse_args()

    print(f"Logging in as {config.f95_user()} ...")
    session = auth.F95Session()
    session.ensure_authenticated()
    print("Authenticated.\n")

    url = THREAD_URL.format(f95_id=args.f95_id)
    print(f"Fetching {url}")
    detail = parse_thread_detail(session.get(url).text)

    downloads = detail.get("downloads") or []
    if args.json:
        print(json.dumps(downloads, indent=2))
        return 0

    print(f"\nParsed {len(downloads)} download link(s):")
    for index, link in enumerate(downloads):
        print(describe_link(index, link))
    for bucket in ("patches", "extras", "translations"):
        count = len(detail.get(bucket) or [])
        if count:
            print(f"  ({count} in '{bucket}', not shown)")

    masked = [link for link in downloads if link.get("masked")]
    print(f"\n{len(masked)} masked, {len(downloads) - len(masked)} unmasked.")

    ids = {user_id_from_masked(link["url"]) for link in masked}
    ids.discard(None)
    if ids:
        print(f"User-id segment(s): {', '.join(sorted(ids))}")

    if not masked:
        print("\nNo masked links; nothing to test.")
        return 0
    if args.dry_run:
        print("\nDry run - stopping before resolution.")
        return 0

    targets = masked if args.all else [masked[min(args.index, len(masked) - 1)]]
    results = []
    for position, link in enumerate(targets):
        print(f"\n{'=' * 70}")
        print(f"Resolving {link.get('host')} ({link.get('label')})")
        save_path = None
        if args.save_body:
            save_path = f"masked_{args.f95_id}_{link.get('host', 'x')}_{position}.html"
        try:
            result = probe_masked(session, link["url"], save_body=save_path,
                                  show_body=not args.no_body)
        except Exception as err:  # noqa: BLE001 - diagnostic
            print(f"  ERROR: {type(err).__name__}: {err}")
            result = {"outcome": "ERROR", "error": str(err)}
        results.append(result)

        outcome = result["outcome"]
        if outcome == "A":
            print(f"\n  => A: clean redirect to {result['host']}")
            if result["host"].endswith("mega.nz") and not result["has_fragment"]:
                print("     ! No #fragment - Mega decryption key missing.")
        elif outcome == "B":
            print("\n  => B: link is in the static html")
            print(f"     {_short(result['destination'])}")
        elif outcome == "C":
            print("\n  => C: real challenge widget - needs a human")
        elif outcome == "D":
            print("\n  => D: no link, no challenge - injected by javascript")
            print("     A real browser will resolve this without interaction.")

    print(f"\n{'=' * 70}")
    print("VERDICT")
    outcomes = [result["outcome"] for result in results]
    if all(outcome == "A" for outcome in outcomes):
        print("  A - fully automatable, no browser required.")
    elif all(outcome in ("A", "B") for outcome in outcomes):
        print("  A/B - automatable by reading the response, no browser.")
    elif "C" in outcomes:
        print("  C - a real challenge is present. Visible browser window,")
        print("      user clears it, cache resolved urls aggressively.")
    elif all(outcome in ("A", "B", "D") for outcome in outcomes):
        print("  D - link is javascript-injected, no challenge found.")
        print("      An Electron window resolves it with no user interaction.")
        print("      Confirm by opening one of these urls in your own browser:")
        print("      if it redirects straight through, this is settled.")
    else:
        print(f"  Mixed: {outcomes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
