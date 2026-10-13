"""Tests for watch matching and the alert decision.

This is the logic that decides whether a stranger's phone buzzes at 21:40, so
it is worth being pedantic about.
"""

from dataclasses import dataclass

import pytest

from tgtg_alert.matcher import WatchRule, build_notification, decide, matches


@dataclass
class FakeItem:
    item_id: str = "1"
    quantity: int = 1
    store_name: str = "Blank Street Coffee"
    display_name: str = "Magic Bag"
    price_minor: int | None = 399
    pickup_end: str | None = None


# -- matching ------------------------------------------------------------


def test_no_patterns_matches_everything():
    watch = WatchRule(id=1)
    assert matches(watch, FakeItem())


def test_store_pattern_is_case_insensitive_substring():
    watch = WatchRule(id=1, store_pattern="blank street")
    assert matches(watch, FakeItem(store_name="Blank Street Coffee"))
    assert matches(watch, FakeItem(store_name="BLANK STREET COFFEE"))


def test_store_pattern_collapses_extra_whitespace():
    watch = WatchRule(id=1, store_pattern="blank  street")
    assert matches(watch, FakeItem(store_name="Blank Street"))


def test_store_pattern_rejects_non_match():
    watch = WatchRule(id=1, store_pattern="Pret")
    assert not matches(watch, FakeItem(store_name="Blank Street Coffee"))


def test_bag_pattern_filters_by_bag_type():
    watch = WatchRule(id=1, store_pattern="blank", bag_pattern="magic")
    assert matches(watch, FakeItem(display_name="Magic Bag"))
    assert not matches(watch, FakeItem(display_name="Bakery Box"))


def test_price_ceiling_excludes_expensive_bags():
    watch = WatchRule(id=1, max_price_minor=500)
    assert matches(watch, FakeItem(price_minor=399))
    assert not matches(watch, FakeItem(price_minor=750))


def test_price_ceiling_allows_unknown_price():
    """An unreadable price must not silently hide a real match."""
    watch = WatchRule(id=1, max_price_minor=500)
    assert matches(watch, FakeItem(price_minor=None))


def test_all_constraints_combine_with_and():
    watch = WatchRule(id=1, store_pattern="blank", bag_pattern="magic", max_price_minor=500)
    assert matches(watch, FakeItem(price_minor=400))
    assert not matches(watch, FakeItem(price_minor=900))


# -- decisions -----------------------------------------------------------


def test_first_ever_poll_is_silent_baseline():
    """Otherwise setup would fire a notification for every bag already there."""
    d = decide(FakeItem(quantity=4), previous_quantity=None, baselined=False)
    assert not d.should_alert
    assert d.reason == "baseline"


def test_restock_alerts_on_zero_to_positive():
    d = decide(FakeItem(quantity=3), previous_quantity=0, baselined=True)
    assert d.should_alert
    assert d.reason == "restock"
    assert d.previous_quantity == 0


def test_new_listing_alerts_after_baseline():
    d = decide(FakeItem(quantity=2), previous_quantity=None, baselined=True)
    assert d.should_alert
    assert d.reason == "new"


def test_steady_stock_stays_quiet():
    """A bag sitting at 4 all afternoon is not news."""
    d = decide(FakeItem(quantity=4), previous_quantity=4, baselined=True)
    assert not d.should_alert
    assert d.reason == "unchanged"


def test_increase_is_quiet_by_default():
    d = decide(FakeItem(quantity=6), previous_quantity=2, baselined=True)
    assert not d.should_alert


def test_increase_alerts_when_opted_in():
    d = decide(FakeItem(quantity=6), previous_quantity=2, baselined=True, notify_on_increase=True)
    assert d.should_alert
    assert d.reason == "increase"


def test_sold_out_never_alerts():
    d = decide(FakeItem(quantity=0), previous_quantity=5, baselined=True)
    assert not d.should_alert
    assert d.reason == "not_in_stock"


def test_sold_out_new_item_never_alerts():
    d = decide(FakeItem(quantity=0), previous_quantity=None, baselined=True)
    assert not d.should_alert


@pytest.mark.parametrize("previous", [1, 2, 10])
def test_any_positive_to_zero_to_positive_cycle_alerts(previous):
    decide(FakeItem(quantity=0), previous_quantity=previous, baselined=True)
    d = decide(FakeItem(quantity=1), previous_quantity=0, baselined=True)
    assert d.should_alert


# -- notification copy ---------------------------------------------------


def test_restock_copy_names_the_bag_and_store():
    item = FakeItem(display_name="Magic Bag", store_name="Blank Street")
    d = decide(item, previous_quantity=0, baselined=True)
    title, body = build_notification(item, d, WatchRule(id=1))
    assert "Magic Bag" in title
    assert "Blank Street" in title
    assert "3 left" in body or "left" in body


def test_new_listing_copy_says_new():
    item = FakeItem()
    d = decide(item, previous_quantity=None, baselined=True)
    title, _ = build_notification(item, d, WatchRule(id=1))
    assert title.startswith("New:")


def test_copy_survives_missing_fields():
    item = FakeItem(display_name="", store_name="", price_minor=None)
    d = decide(item, previous_quantity=0, baselined=True)
    title, body = build_notification(item, d, WatchRule(id=1))
    assert title and body
