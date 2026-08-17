"""Per-source scraper agents."""


class RefreshOutcome:
    """Result of a single-item refresh.

    Every agent's `refresh_one` used to return a bare bool, so the queue
    worker had no way to say WHY a row failed and wrote one hardcoded string
    ("detail fetch failed, or not yet mapped") for causes as different as a
    transient HTTP 403 and a deliberate refusal to guess at a mapping. The
    queue row then carried no usable signal at all.

    Truthy/falsy on `ok`, so existing `if agent.refresh_one(...)` callers
    (tools/refresh/*.py) keep working unchanged.

    Attributes:
        ok:      did the refresh write anything
        code:    stable machine-readable reason, e.g. "linked", "no_mapping"
        message: human-readable detail, stored in f95_refresh_queue.last_error
    """

    __slots__ = ("ok", "code", "message")

    def __init__(self, ok, code, message=""):
        self.ok = bool(ok)
        self.code = code
        self.message = message or code

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return f"RefreshOutcome(ok={self.ok}, code={self.code!r})"


def as_outcome(result, ok_code="refreshed", fail_code="failed"):
    """Normalise a bool-or-RefreshOutcome into a RefreshOutcome."""
    if isinstance(result, RefreshOutcome):
        return result
    if result:
        return RefreshOutcome(True, ok_code)
    return RefreshOutcome(False, fail_code)
