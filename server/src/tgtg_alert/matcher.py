"""Watch-rule matching and the 0 -> >0 alert decision.

Deliberately free of I/O so the behaviour that actually matters -- *when do we
wake someone up* -- is testable without TGTG credentials.

The decision rules, and why:

* **First observation of a watch is a silent baseline.** Otherwise the very
  first poll alerts on every bag already in stock, and the user's first
  experience is a burst of twenty notifications.
* **0 -> >0 alerts.** This is the main event: a sold-out bag came back.
* **An item first seen *after* the baseline with stock alerts** -- it is a
  genuinely new listing, which is the other half of "tell me when this shows
  up". (Before the baseline it would have been part of the flood.)
* **Still-in-stock stays quiet.** A bag sitting at quantity 4 for six hours is
  not news, and re-alerting is how you get muted.
* **Stock increasing while already > 0 stays quiet by default** (a "more bags
  arrived" ping is available per-watch, but off, because it doubles the noise
  for a marginal gain).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    """Casefold and collapse whitespace so 'Blank  Street' matches 'blank street'."""
    if not value:
        return ""
    return _WHITESPACE.sub(" ", value).strip().casefold()


class ItemLike(Protocol):
    item_id: str
    quantity: int
    store_name: str
    display_name: str
    price_minor: int | None


@dataclass
class WatchRule:
    id: int
    store_pattern: str | None = None
    bag_pattern: str | None = None
    max_price_minor: int | None = None
    latitude: float = 0.0
    longitude: float = 0.0
    radius_km: int = 10
    enabled: bool = True
    baselined: bool = False
    notify_on_increase: bool = False

    @property
    def label(self) -> str:
        bits = [b for b in (self.store_pattern, self.bag_pattern) if b]
        return " @ ".join(bits) if bits else f"{self.radius_km}km around you"


def matches(watch: WatchRule, item: ItemLike) -> bool:
    """True when `item` satisfies every constraint the watch sets.

    A watch with no patterns matches everything in radius -- that is the
    intentional "any bag near me" rule. Constraints combine with AND; each is
    individually optional.
    """
    if watch.store_pattern:
        needle = normalize_text(watch.store_pattern)
        if needle not in normalize_text(item.store_name):
            return False

    if watch.bag_pattern:
        needle = normalize_text(watch.bag_pattern)
        if needle not in normalize_text(item.display_name):
            return False

    if watch.max_price_minor is not None:
        # An item with no readable price can't be proven to be under the
        # ceiling. Excluding it silently would hide real matches, so it passes.
        if item.price_minor is not None and item.price_minor > watch.max_price_minor:
            return False

    return True


@dataclass
class Decision:
    should_alert: bool
    reason: str  # "restock" | "new" | "increase" | "baseline" | "unchanged" | "not_in_stock"
    previous_quantity: int | None
    quantity: int

    @property
    def is_page_load(self) -> bool:
        return self.reason == "baseline"


def decide(
    item: ItemLike,
    previous_quantity: int | None,
    *,
    baselined: bool,
    notify_on_increase: bool = False,
) -> Decision:
    """Decide whether this observation warrants waking someone up.

    `previous_quantity` is None when the item has never been seen for this
    watch. `baselined` says whether the watch has completed an initial poll.
    """
    qty = item.quantity

    if qty <= 0:
        return Decision(False, "not_in_stock", previous_quantity, qty)

    if previous_quantity is None:
        # Never seen before. If the watch has no baseline yet this is just the
        # initial survey; otherwise a genuinely new listing has appeared.
        if not baselined:
            return Decision(False, "baseline", None, qty)
        return Decision(True, "new", None, qty)

    if previous_quantity <= 0 < qty:
        return Decision(True, "restock", previous_quantity, qty)

    if qty > previous_quantity and notify_on_increase:
        return Decision(True, "increase", previous_quantity, qty)

    return Decision(False, "unchanged", previous_quantity, qty)


def build_notification(item: ItemLike, decision: Decision, watch: WatchRule) -> tuple[str, str]:
    """Compose the push title and body.

    Kept short: Android and iOS both truncate, and the useful information is
    "what" and "how many", not prose.
    """
    name = item.display_name or "Surprise bag"
    store = item.store_name or "a store"

    if decision.reason == "restock":
        title = f"{name} is back at {store}"
    elif decision.reason == "new":
        title = f"New: {name} at {store}"
    else:
        title = f"More {name} at {store}"

    price = getattr(item, "price_minor", None)
    window = ""
    pickup_end = getattr(item, "pickup_end", None)
    if pickup_end:
        # TGTG sends ISO-8601; the time-of-day is what matters in a notification.
        window = f" · collect by {str(pickup_end)[11:16]}"

    money = f"{price / 100:.2f}" if isinstance(price, int) else "?"
    remaining = f"{decision.quantity} left"
    body = f"{remaining} · {money}{window}"

    return title, body
