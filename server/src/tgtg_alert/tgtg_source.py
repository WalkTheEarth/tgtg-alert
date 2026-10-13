"""Thin, defensive wrapper around the unofficial `tgtg` client.

Two concerns live here that the upstream library does not handle for a
long-running server:

1. **Credential persistence, including `last_time_token_refreshed`.**
   `TgtgClient.login()` (called internally by every `get_items`) refreshes the
   access token unless it was refreshed within `access_token_lifetime`. When
   that timestamp is `None` -- which it is on a freshly constructed client --
   *every single call* triggers a refresh. For a poller running every few
   minutes that doubles our request volume against an undocumented, rate-limited
   API. So we persist and restore it.

2. **Response normalisation.** `get_items()` returns raw JSON dicts straight
   from the API with no mapping. Field names are undocumented and have moved
   before (item/v7 -> item/v8), so extraction tries several known paths and
   records what it could not find rather than raising.

Nothing here is verified against live credentials; see `KNOWN_SHAPES` for the
paths we accept and `tests/test_normalize.py` for the shapes exercised.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from tgtg import TgtgClient
from tgtg.exceptions import TgtgAPIError

from .config import ACCESS_TOKEN_LIFETIME_SECONDS, DEFAULT_USER_AGENT, USER_AGENT_TEMPLATE

log = logging.getLogger(__name__)


def user_agent_for(
    explicit: str | None = None,
    stored: str | None = None,
) -> str:
    """Pick the User-Agent to present, in strict precedence order.

    `explicit` (the TGTG_USER_AGENT env var) always wins -- someone who sets it
    means it. Otherwise the value captured at login is reused, because the
    DataDome cookie is bound to it and presenting a different one later reads as
    a cookie replay and gets a 403. The pinned default is the last resort.

    Getting this precedence wrong is subtle and expensive: login under one UA
    and poll under another, and everything looks configured correctly while
    every request is refused.
    """
    return explicit or stored or DEFAULT_USER_AGENT


def discover_current_user_agent() -> tuple[str, bool]:
    """Build a User-Agent from TGTG's current Play Store version.

    Returns (user_agent, resolved_live). The scrape parses a Play Store payload
    whose shape Google changes without notice, so failure is expected sometimes
    and falls back to the pinned default rather than blocking login.
    """
    try:
        from tgtg import get_last_apk_version

        version = get_last_apk_version()
        if version and str(version).strip():
            return USER_AGENT_TEMPLATE.format(str(version).strip()), True
    except Exception as exc:  # noqa: BLE001 - best effort by design
        log.debug("could not determine the current TGTG version: %s", exc)
    return DEFAULT_USER_AGENT, False

# HTTP 429 is TGTG's documented-nowhere rate-limit signal. 403 is what DataDome
# bot protection returns when it decides we look like a script.
RATE_LIMIT_STATUS = 429
FORBIDDEN_STATUS = 403


class CredentialsMissing(RuntimeError):
    """No TGTG credentials on file -- run `tgtg-alert login`."""


def _dig(payload: dict, *paths: str, default=None):
    """Return the first path that resolves to a non-None value.

    Each path is dotted; a path segment addressing a list indexes into it.
    Lets us accept `store.store_name` and `store_name` without branching at
    every call site.
    """
    for path in paths:
        cur: Any = payload
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default


def _money_to_minor(value: Any) -> int | None:
    """Normalise a TGTG price object to an integer in minor units (cents).

    The API sends `{"code": "EUR", "minor_units": 399, "decimals": 2}`, but
    some responses use a plain number. Both are accepted.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        minor = value.get("minor_units")
        if isinstance(minor, (int, float)):
            return int(minor)
        amount = value.get("amount")
        if isinstance(amount, (int, float)):
            decimals = value.get("decimals", 2)
            return int(round(float(amount) * (10 ** int(decimals))))
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value) * 100))
    return None


def _money_code(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("code")
    return None


@dataclass
class Item:
    """A normalised TGTG item -- the only shape the rest of the app sees."""

    item_id: str
    quantity: int
    store_id: str | None = None
    store_name: str = ""
    display_name: str = ""
    price_minor: int | None = None
    currency: str | None = None
    item_category: str | None = None
    in_sales_window: bool | None = None
    pickup_start: str | None = None
    pickup_end: str | None = None
    distance_m: int | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def price_display(self) -> str:
        if self.price_minor is None:
            return "?"
        return f"{self.price_minor / 100:.2f}"


def normalize_item(payload: dict) -> Item | None:
    """Convert one raw API item into an `Item`, or None if unusable.

    Returns None rather than raising so one malformed entry in a page of twenty
    does not lose the other nineteen.
    """
    if not isinstance(payload, dict):
        return None

    item_id = _dig(payload, "item_id", "itemId", "id")
    if item_id is None:
        log.warning("item with no id, skipping: keys=%s", sorted(payload)[:12])
        return None

    quantity = _dig(payload, "items_available", "itemsAvailable", default=0)
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 0

    price_raw = _dig(payload, "price_including_taxes", "priceIncludingTaxes", "price")

    # Pickup window lives under `pickup_interval` in most responses, but the
    # library's own test constants list `collection_info` and `pickup_location`.
    pickup_start = _dig(
        payload,
        "pickup_interval.start",
        "pickup_interval.start_date",
        "collection_info.pickup_start",
        "pickup_start",
    )
    pickup_end = _dig(
        payload,
        "pickup_interval.end",
        "pickup_interval.end_date",
        "collection_info.pickup_end",
        "pickup_end",
    )

    return Item(
        item_id=str(item_id),
        quantity=max(0, quantity),
        store_id=_dig(payload, "store.store_id", "store_id"),
        store_name=str(_dig(payload, "store.store_name", "store_name", default="") or ""),
        display_name=str(_dig(payload, "display_name", "displayName", "name", default="") or ""),
        price_minor=_money_to_minor(price_raw),
        currency=_money_code(price_raw),
        item_category=_dig(payload, "item_category", "itemCategory"),
        in_sales_window=_dig(payload, "in_sales_window", "inSalesWindow"),
        pickup_start=str(pickup_start) if pickup_start else None,
        pickup_end=str(pickup_end) if pickup_end else None,
        distance_m=_dig(payload, "store.distance", "distance"),
        raw=payload,
    )


def normalize_page(items: Any) -> list[Item]:
    if not isinstance(items, list):
        log.warning("expected a list of items, got %s", type(items).__name__)
        return []
    out = []
    for raw in items:
        item = normalize_item(raw)
        if item is not None:
            out.append(item)
    return out


class TgtgBlocked(RuntimeError):
    """DataDome refused the request (HTTP 403) -- we look like a bot.

    Distinct from a rate limit: this is a verdict on our fingerprint, not a
    quota. Retrying makes it worse, and the upstream client has already burned
    one extra request pair fetching a fresh cookie, so the only sane response
    is to stop for a long time.
    """

    def __init__(self, retry_after: float = 0.0, detail: str = ""):
        super().__init__(detail or "blocked by DataDome (HTTP 403)")
        self.retry_after = retry_after


class TgtgRateLimited(RuntimeError):
    """The API returned 429. A quota, not a verdict -- back off and resume."""

    def __init__(self, retry_after: float = 0.0):
        super().__init__("rate limited by TGTG (HTTP 429)")
        self.retry_after = retry_after


class Pacer:
    """Spaces outbound calls and manages escalating backoff.

    Process-wide and deliberately simple: the poller is single-threaded, so a
    lock plus timestamps is enough, and it keeps the behaviour obvious.

    Backoff is separate from spacing. Spacing is the polite steady state;
    backoff is what happens after TGTG tells us to stop, and it must survive
    across polls -- a block that is forgotten on the next pass is not a backoff
    at all.
    """

    def __init__(self, min_interval_seconds: float, block_backoff_seconds: float = 3600.0):
        self.min_interval = max(0.0, min_interval_seconds)
        self.block_backoff = block_backoff_seconds
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._blocked_until = 0.0
        self.consecutive_blocks = 0
        self.consecutive_rate_limits = 0

    # -- spacing ----------------------------------------------------------

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            target = max(self._last_call + self.min_interval, self._blocked_until)
            delay = target - now
            if delay > 0:
                time.sleep(delay)
            self._last_call = time.monotonic()

    @property
    def blocked_for(self) -> float:
        """Seconds until the current block lifts (0 when not blocked)."""
        with self._lock:
            return max(0.0, self._blocked_until - time.monotonic())

    @property
    def is_blocked(self) -> bool:
        return self.blocked_for > 0

    # -- outcomes ---------------------------------------------------------

    def note_success(self) -> None:
        with self._lock:
            self.consecutive_rate_limits = 0
            # Deliberately does NOT clear consecutive_blocks: a tracker that
            # starts working again should still be treated as suspect for a
            # while, because the classic failure is "fine for 30 minutes, then
            # blocked on the first token refresh".
            if self.consecutive_blocks and self._blocked_until <= time.monotonic():
                self.consecutive_blocks = max(0, self.consecutive_blocks - 1)

    def note_rate_limited(self) -> float:
        """Record a 429; returns how long to hold off."""
        with self._lock:
            self.consecutive_rate_limits += 1
            # 60s, 120s, 240s, ... capped at 30 minutes.
            delay = min(60 * (2 ** (self.consecutive_rate_limits - 1)), 1800)
            self._blocked_until = max(self._blocked_until, time.monotonic() + delay)
            return float(delay)

    def note_blocked(self) -> float:
        """Record a DataDome 403; returns how long to hold off.

        Escalates: an hour, then two, then four, capped at six. A first block
        is often transient (a rotated cookie, a flaky exit IP); a second means
        the fingerprint is genuinely burned and hammering will only deepen it.
        """
        with self._lock:
            self.consecutive_blocks += 1
            delay = min(self.block_backoff * (2 ** (self.consecutive_blocks - 1)), 6 * 3600)
            self._blocked_until = max(self._blocked_until, time.monotonic() + delay)
            return float(delay)


class TgtgSource:
    """Fetches and normalises items, caching pages per location bucket."""

    # Minimum spacing between outbound calls. One call per 2s is far below any
    # plausible limit while still allowing a multi-page scan.
    MIN_CALL_SPACING = 2.0

    def __init__(
        self,
        credentials: dict,
        language: str = "en-GB",
        timeout: float = 20.0,
        user_agent: str | None = None,
        block_backoff_seconds: float = 3600.0,
    ):
        self.credentials = credentials
        self.language = language
        self.timeout = timeout
        self.user_agent = user_agent
        self.pacer = Pacer(self.MIN_CALL_SPACING, block_backoff_seconds=block_backoff_seconds)
        self._client: TgtgClient | None = None

    # -- client lifecycle -------------------------------------------------

    def _build_client(self) -> TgtgClient:
        creds = self.credentials
        refreshed_at = creds.get("last_time_token_refreshed")
        parsed: _dt.datetime | None = None
        if refreshed_at:
            try:
                parsed = _dt.datetime.fromisoformat(refreshed_at)
            except (TypeError, ValueError):
                parsed = None

        return TgtgClient(
            access_token=creds["access_token"],
            refresh_token=creds["refresh_token"],
            cookie=creds["cookie"],
            email=creds.get("email"),
            language=self.language,
            timeout=self.timeout,
            last_time_token_refreshed=parsed,
            access_token_lifetime=ACCESS_TOKEN_LIFETIME_SECONDS,
            # Never let the library pick its own: it scrapes Google Play on
            # every construction (slow, noisy on stdout) and falls back to a
            # version about a year stale. Worse, that pick would be its own,
            # breaking the match with the UA the DataDome cookie was issued to.
            user_agent=user_agent_for(self.user_agent, creds.get("user_agent")),
        )

    @property
    def client(self) -> TgtgClient:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def capture_credentials(self) -> dict:
        """Read back the (possibly refreshed) credentials from the client.

        The library refreshes tokens internally during `get_items`, so we have
        to harvest whatever it ended up with and persist it -- otherwise the
        next process start re-refreshes and we double our call volume.
        """
        client = self.client
        refreshed = client.last_time_token_refreshed
        return {
            "access_token": client.access_token,
            "refresh_token": client.refresh_token,
            "cookie": client.cookie,
            "last_time_token_refreshed": refreshed.isoformat() if refreshed else None,
        }

    # -- fetching ---------------------------------------------------------

    def fetch_items(
        self,
        latitude: float,
        longitude: float,
        radius_km: int,
        page_size: int = 20,
        max_pages: int = 3,
    ) -> list[Item]:
        """Fetch every item near a point.

        `with_stock_only=False` is essential: we need to observe sold-out items
        too, because the whole alert mechanism is the 0 -> >0 transition. Asking
        only for in-stock items would make every result look like a new arrival.
        """
        collected: list[Item] = []
        for page in range(1, max_pages + 1):
            self.pacer.wait()
            try:
                raw_items = self.client.get_items(
                    latitude=latitude,
                    longitude=longitude,
                    radius=radius_km,
                    page_size=page_size,
                    page=page,
                    favorites_only=False,
                    with_stock_only=False,
                    discover=False,
                )
            except TgtgAPIError as exc:
                raise self._classify(exc) from exc
            else:
                self.pacer.note_success()

            page_items = normalize_page(raw_items)
            collected.extend(page_items)

            if len(raw_items) < page_size:
                break

        return collected

    def _classify(self, exc: TgtgAPIError) -> Exception:
        """Turn an upstream error into one the poller knows how to react to.

        Careful not to retry here: the upstream client already retried a 403
        once with a fresh DataDome cookie, so every block has already cost two
        request pairs. Adding our own retry on top is how a temporary block
        becomes a permanent one.
        """
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)

        if status == FORBIDDEN_STATUS:
            delay = self.pacer.note_blocked()
            log.error(
                "TGTG refused the request (HTTP 403 / DataDome); backing off %d min.\n"
                "  Most likely causes, in order:\n"
                "    1. A datacenter or VPN IP. DataDome blocks these -- a home "
                "connection is far more reliable than a VPS.\n"
                "    2. A stale User-Agent. Set TGTG_USER_AGENT to a current TGTG "
                "app version.\n"
                "    3. Polling too often. Raise TGTG_POLL_INTERVAL.\n"
                "  Nothing is broken; alerts resume on their own once it clears.",
                round(delay / 60),
            )
            return TgtgBlocked(retry_after=delay, detail=str(exc))

        if status == RATE_LIMIT_STATUS:
            delay = self.pacer.note_rate_limited()
            log.warning("rate limited by TGTG (HTTP 429); backing off %ds", round(delay))
            return TgtgRateLimited(retry_after=delay)

        return exc


# -- development ---------------------------------------------------------

FIXTURE_TEMPLATE = {
    "_comment": [
        "Sample TGTG Alert fixture. Poll from this instead of the live API by",
        "setting TGTG_DEV_MODE=1 and TGTG_DEV_FIXTURE to this file's path.",
        "",
        "To watch an alert fire: set items_available to 0, run one poll (the item",
        "is recorded as sold out), then set it back to 3 and poll again. That is",
        "the 0 -> >0 transition, and it should notify you.",
        "",
        "Deleting an item entirely is equivalent to setting it to 0, which is how",
        "absence-as-sold-out is tested.",
        "",
        "Add a \"simulate\" block to test the failure paths, e.g.",
        "  \"simulate\": {\"status\": 403}   -> acts blocked by DataDome",
        "  \"simulate\": {\"status\": 429}   -> acts rate limited",
    ],
    "items": [
        {
            "item_id": "1001",
            "display_name": "Magic Bag",
            "item_category": "MEALS",
            "items_available": 2,
            "in_sales_window": True,
            "price_including_taxes": {"code": "GBP", "minor_units": 399, "decimals": 2},
            "pickup_interval": {"start": "2026-01-01T18:00:00Z", "end": "2026-01-01T19:00:00Z"},
            "store": {"store_id": "s1", "store_name": "Blank Street Coffee", "distance": 450},
        },
        {
            "item_id": "1002",
            "display_name": "Bakery Box",
            "item_category": "BAKERY",
            "items_available": 0,
            "price_including_taxes": {"code": "GBP", "minor_units": 300, "decimals": 2},
            "store": {"store_id": "s2", "store_name": "Pret A Manger", "distance": 900},
        },
        {
            "item_id": "1003",
            "display_name": "Sushi Box",
            "item_category": "SUSHI",
            "items_available": 1,
            "price_including_taxes": {"code": "GBP", "minor_units": 599, "decimals": 2},
            "store": {"store_id": "s3", "store_name": "Itsu", "distance": 2400},
        },
    ],
}


class FixtureSource:
    """Serves items from a local JSON file instead of the live API.

    Exists because the alert path is otherwise close to untestable: the whole
    mechanism is a 0 -> >0 transition, and you cannot make a real shop restock on
    demand. With a fixture you flip a number, poll, and watch the real matcher,
    the real database writes, and the real push fire.

    The file is re-read on **every** fetch, so editing it between polls is the
    intended way to drive a transition -- which also means a typo is reported at
    poll time, not silently cached.
    """

    def __init__(self, path, block_backoff_seconds: float = 3600.0):
        self.path = path
        self.pacer = Pacer(0.0, block_backoff_seconds=block_backoff_seconds)
        self.fetch_count = 0

    def _load(self) -> tuple[list[dict], dict | None]:
        try:
            raw = self.path.read_text()
        except FileNotFoundError:
            raise RuntimeError(
                f"TGTG_DEV_FIXTURE points at {self.path}, which does not exist.\n"
                "Generate one with `tgtg-alert dev fixture --write`."
            ) from None

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.path} is not valid JSON: {exc}") from exc

        if isinstance(payload, list):
            return payload, None
        if isinstance(payload, dict):
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise RuntimeError(f'{self.path}: "items" must be a list')
            simulate = payload.get("simulate")
            return items, simulate if isinstance(simulate, dict) else None
        raise RuntimeError(f"{self.path}: expected a list of items or an object with an 'items' key")

    def fetch_items(
        self,
        latitude: float,
        longitude: float,
        radius_km: int,
        page_size: int = 20,
        max_pages: int = 3,
    ) -> list[Item]:
        self.fetch_count += 1
        raw_items, simulate = self._load()

        if simulate:
            status = simulate.get("status")
            if status == FORBIDDEN_STATUS:
                delay = self.pacer.note_blocked()
                log.warning("[fixture] simulating HTTP 403 (DataDome); backing off %d min",
                            round(delay / 60))
                raise TgtgBlocked(retry_after=delay, detail="simulated 403")
            if status == RATE_LIMIT_STATUS:
                delay = self.pacer.note_rate_limited()
                log.warning("[fixture] simulating HTTP 429; backing off %ds", round(delay))
                raise TgtgRateLimited(retry_after=delay)
            if status:
                raise TgtgAPIError(int(status), b"simulated error")

        items = normalize_page(raw_items)

        # Apply the same radius bound the real path applies, so a fixture can
        # test that distance filtering works.
        limit_m = radius_km * 1000
        items = [i for i in items if i.distance_m is None or i.distance_m <= limit_m]

        log.info("[fixture] serving %d item(s) from %s (fetch #%d)",
                 len(items), self.path.name, self.fetch_count)
        return items

    def capture_credentials(self) -> dict | None:
        """Nothing to persist -- a fixture has no session."""
        return None
