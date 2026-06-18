"""
F95 authenticated session.

Strategy (per requirements):
  - Log in once with the dummy account credentials from .env.
  - Persist the resulting cookies to disk.
  - On every run, reuse the cached cookie and only log in again when it
    has expired. This avoids logging in on every scrape.

F95zone runs XenForo 2. Login is a POST to /login/login with the page's
CSRF token (_xfToken). A live session is verified by the `data-logged-in`
attribute on the root <html> element of any page.
"""
import json
import os
import re
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scraper.config import config

# Use the OS trust store (Windows/corporate/AV roots) for TLS verification.
# Fixes "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate"
# on machines where antivirus or a proxy does HTTPS inspection.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

BASE = "https://f95zone.to"

# A normal desktop UA. F95 serves the "you must be registered" gating to
# anything it treats as a guest, so the cookie — not the UA — is what matters,
# but a real UA avoids tripping bot heuristics.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class AuthError(RuntimeError):
    pass


class XenForoSession:
    """Generic XenForo 2.x authenticated session: cookie persistence + lazy
    login + liveness via the `data-logged-in` flag. Subclasses set the site
    BASE and supply credentials/cookie-file accessors.

    Both F95zone and LewdCorner run XenForo, so the login flow (POST to
    /login/login with the page's _xfToken) and the liveness signal are
    identical; only the base URL and which .env credentials to use differ.
    """

    BASE = ""  # subclass sets this, e.g. "https://f95zone.to"

    def __init__(self, cookie_file):
        self.cookie_file = cookie_file
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._authenticated = False
        self._load_cookies()

    # ---- credentials (subclass overrides) ----------------------------------
    def _credentials(self):
        """Return (user, password) for login. Overridden per site."""
        raise NotImplementedError

    # ---- cookie persistence -------------------------------------------------
    def _load_cookies(self):
        if not os.path.exists(self.cookie_file):
            return
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as fh:
                for c in json.load(fh):
                    self.session.cookies.set(
                        c["name"], c["value"],
                        domain=c.get("domain"), path=c.get("path", "/"),
                    )
        except (ValueError, KeyError, OSError):
            # Corrupt cookie cache -> ignore and re-login later.
            pass

    def _save_cookies(self):
        data = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.session.cookies
        ]
        tmp = self.cookie_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.cookie_file)

    # ---- session state ------------------------------------------------------
    @staticmethod
    def _is_logged_in_html(html):
        # The root <html> tag carries data-logged-in="true"/"false".
        # Cheap string check avoids a full parse just for the flag.
        head = html[:2000]
        if 'data-logged-in="true"' in head:
            return True
        if 'data-logged-in="false"' in head:
            return False
        # Fall back to a full parse if the attribute moved.
        tag = BeautifulSoup(html, "lxml").find("html")
        return bool(tag and tag.get("data-logged-in") == "true")

    def is_logged_in(self):
        """Hit a lightweight page and read the login flag."""
        try:
            r = self.session.get(self.BASE + "/account/", timeout=30,
                                  allow_redirects=True)
        except requests.RequestException:
            return False
        return r.status_code == 200 and self._is_logged_in_html(r.text)

    def login(self):
        """Full XenForo login using credentials from .env."""
        user, password = self._credentials()

        # 1. GET the login form to obtain the CSRF token.
        r = self.session.get(self.BASE + "/login/login", timeout=30)
        if r.status_code != 200:
            raise AuthError(f"Could not load login page (HTTP {r.status_code})")
        soup = BeautifulSoup(r.text, "lxml")
        token_input = soup.find("input", attrs={"name": "_xfToken"})
        token = token_input["value"] if token_input and token_input.has_attr("value") else ""

        # 2. POST credentials.
        payload = {
            "login": user,
            "password": password,
            "remember": "1",
            "_xfRedirect": self.BASE + "/",
            "_xfToken": token,
        }
        headers = {"Referer": self.BASE + "/login/login",
                   "Origin": self.BASE}
        r = self.session.post(self.BASE + "/login/login", data=payload,
                              headers=headers, timeout=30, allow_redirects=True)

        if not self._is_logged_in_html(r.text) and not self.is_logged_in():
            raise AuthError(
                f"Login failed for {self.BASE}. Check the account credentials "
                "in .env, and whether the account triggered a captcha."
            )
        self._authenticated = True
        self._save_cookies()

    def ensure_authenticated(self):
        """Reuse the cached cookie; only log in when it has expired."""
        if self._authenticated:
            return
        if self.is_logged_in():
            self._authenticated = True
            # Refresh the on-disk copy in case cookies rotated.
            self._save_cookies()
            return
        self.login()

    # ---- request helpers ----------------------------------------------------
    def get(self, url, **kwargs):
        """Authenticated GET. Verifies the session is live, retrying login
        once if the cookie expired mid-run."""
        self.ensure_authenticated()
        kwargs.setdefault("timeout", 30)
        r = self.session.get(url, **kwargs)
        # If F95 silently logged us out, re-auth once and retry.
        if r.status_code == 200 and not self._is_logged_in_html(r.text):
            self._authenticated = False
            self.login()
            r = self.session.get(url, **kwargs)
        return r

    def get_json(self, url, **kwargs):
        """Authenticated GET that returns parsed JSON (or None).

        Used for the LewdCorner latest-updates.php?api=1 feed: it returns JSON
        rather than HTML, so the data-logged-in HTML check in get() doesn't
        apply. We ensure auth up front; if the feed comes back as a login/HTML
        page (cookie died), we re-auth once and retry.
        """
        self.ensure_authenticated()
        kwargs.setdefault("timeout", 30)
        r = self.session.get(url, **kwargs)
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "json" not in ct.lower():
            # Probably got served an HTML page because the session lapsed.
            if not self._is_logged_in_html(r.text):
                self._authenticated = False
                self.login()
                r = self.session.get(url, **kwargs)
        try:
            return r.json()
        except ValueError:
            return None


class F95Session(XenForoSession):
    """F95zone session (behaviour unchanged from the original)."""

    BASE = "https://f95zone.to"

    def __init__(self, cookie_file=None):
        super().__init__(cookie_file or config.f95_cookie_file())

    def _credentials(self):
        return config.f95_user(), config.f95_password()

    def resolve_masked(self, url):
        """Resolve an F95 /masked/ link to its real destination URL.

        Masked tokens are encrypted server-side and cannot be decoded
        offline, so this makes ONE network request (authenticated) and reads
        the redirect target. Resolve lazily/on demand — not for every mirror
        on every scrape — to avoid rate limiting.

        Returns the destination URL, or None if it couldn't be resolved.
        (Untested against the live site from the build sandbox; verify on a
        machine that can reach f95zone.to.)
        """
        if "/masked/" not in (url or ""):
            return url
        self.ensure_authenticated()
        try:
            r = self.session.get(url, timeout=30, allow_redirects=False)
            loc = r.headers.get("Location")
            if loc and "/masked/" not in loc:
                return loc
            r = self.session.get(url, timeout=30, allow_redirects=True)
        except requests.RequestException:
            return None
        if r.url and "f95zone.to" not in urlparse(r.url).netloc:
            return r.url
        m = re.search(r'href="(https?://[^"]+)"[^>]*link--external', r.text)
        return m.group(1) if m else None


class LCSession(XenForoSession):
    """LewdCorner session. Same XenForo login as F95; only the base URL and
    credentials differ. The latest-updates.php?api=1 feed is fetched with
    get_json() through this authenticated session."""

    BASE = "https://lewdcorner.com"

    def __init__(self, cookie_file=None):
        super().__init__(cookie_file or config.lc_cookie_file())

    def _credentials(self):
        return config.lc_user(), config.lc_password()
