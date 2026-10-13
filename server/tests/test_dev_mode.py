"""Tests for dev mode: the fixture source and its configuration guards.

The fixture exists so the alert path can be exercised without waiting for a real
shop to restock, which also makes the failure paths (403, 429) testable on
demand rather than only when they happen to occur.
"""

import json

import pytest

from tgtg_alert.config import (
    DEV_MIN_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS,
    Config,
    ConfigError,
)
from tgtg_alert.tgtg_source import FixtureSource, TgtgBlocked, TgtgRateLimited

ITEM = {
    "item_id": "1",
    "display_name": "Magic Bag",
    "items_available": 2,
    "store": {"store_name": "Blank Street", "distance": 400},
}


def write_fixture(tmp_path, payload):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload)
    return path


# -- loading -------------------------------------------------------------


def test_reads_object_form(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, {"items": [ITEM]}))
    items = source.fetch_items(51.5, -0.1, 5)
    assert len(items) == 1
    assert items[0].item_id == "1"
    assert items[0].store_name == "Blank Street"


def test_reads_bare_list_form(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, [ITEM]))
    assert len(source.fetch_items(51.5, -0.1, 5)) == 1


def test_rereads_on_every_fetch(tmp_path):
    """Editing between polls is the whole point -- a cached read would make the
    tool useless for driving a transition."""
    path = write_fixture(tmp_path, {"items": [ITEM]})
    source = FixtureSource(path)

    assert source.fetch_items(51.5, -0.1, 5)[0].quantity == 2

    path.write_text(json.dumps({"items": [{**ITEM, "items_available": 0}]}))
    assert source.fetch_items(51.5, -0.1, 5)[0].quantity == 0


def test_applies_radius_filter(tmp_path):
    far = {
        "item_id": "2",
        "items_available": 1,
        "store": {"store_name": "Far Away", "distance": 20_000},
    }
    source = FixtureSource(write_fixture(tmp_path, {"items": [ITEM, far]}))
    assert len(source.fetch_items(51.5, -0.1, 5)) == 1


def test_items_without_distance_are_kept(tmp_path):
    """An unknown distance must not silently drop an item."""
    no_distance = {"item_id": "3", "items_available": 1, "store": {"store_name": "?"}}
    source = FixtureSource(write_fixture(tmp_path, {"items": [ITEM, no_distance]}))
    assert len(source.fetch_items(51.5, -0.1, 5)) == 2


def test_has_no_credentials_to_capture(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, {"items": [ITEM]}))
    assert source.capture_credentials() is None


# -- failure paths -------------------------------------------------------


def test_simulates_a_datadome_block(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, {"items": [ITEM], "simulate": {"status": 403}}))
    with pytest.raises(TgtgBlocked) as exc:
        source.fetch_items(51.5, -0.1, 5)
    assert exc.value.retry_after > 0


def test_simulates_a_rate_limit(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, {"items": [ITEM], "simulate": {"status": 429}}))
    with pytest.raises(TgtgRateLimited):
        source.fetch_items(51.5, -0.1, 5)


def test_block_backoff_escalates_across_fetches(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, {"items": [ITEM], "simulate": {"status": 403}}))
    delays = []
    for _ in range(3):
        with pytest.raises(TgtgBlocked) as exc:
            source.fetch_items(51.5, -0.1, 5)
        delays.append(exc.value.retry_after)
    assert delays == sorted(delays) and delays[0] < delays[-1]


def test_missing_file_explains_itself(tmp_path):
    source = FixtureSource(tmp_path / "nope.json")
    with pytest.raises(RuntimeError, match="does not exist"):
        source.fetch_items(51.5, -0.1, 5)


def test_malformed_json_explains_itself(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, "{ not json"))
    with pytest.raises(RuntimeError, match="not valid JSON"):
        source.fetch_items(51.5, -0.1, 5)


def test_items_key_must_be_a_list(tmp_path):
    source = FixtureSource(write_fixture(tmp_path, {"items": "nope"}))
    with pytest.raises(RuntimeError, match="must be a list"):
        source.fetch_items(51.5, -0.1, 5)


# -- configuration guards ------------------------------------------------


def test_fixture_without_dev_mode_is_refused(monkeypatch, tmp_path):
    """The dangerous half-configuration: the operator believes they are on a
    fixture while the poller quietly talks to the live API."""
    monkeypatch.setenv("TGTG_DEV_FIXTURE", str(tmp_path / "f.json"))
    monkeypatch.delenv("TGTG_DEV_MODE", raising=False)
    with pytest.raises(ConfigError, match="TGTG_DEV_MODE"):
        Config.from_env()


def test_fixture_lowers_the_poll_floor(monkeypatch, tmp_path):
    monkeypatch.setenv("TGTG_DEV_MODE", "1")
    monkeypatch.setenv("TGTG_DEV_FIXTURE", str(tmp_path / "f.json"))
    monkeypatch.setenv("TGTG_POLL_INTERVAL", "20")
    assert Config.from_env().poll_interval == 20


def test_dev_mode_alone_keeps_the_production_floor(monkeypatch):
    """Fast polling against the live API is how accounts get blocked, so dev
    mode without a fixture must not unlock it."""
    monkeypatch.setenv("TGTG_DEV_MODE", "1")
    monkeypatch.delenv("TGTG_DEV_FIXTURE", raising=False)
    monkeypatch.setenv("TGTG_POLL_INTERVAL", "20")
    config = Config.from_env()
    assert config.dev_mode is True
    assert config.dev_fixture is None
    assert config.poll_interval == MIN_POLL_INTERVAL_SECONDS


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "enabled"])
def test_dev_mode_accepts_common_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv("TGTG_DEV_MODE", value)
    assert Config.from_env().dev_mode is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_dev_mode_is_off_by_default(monkeypatch, value):
    monkeypatch.setenv("TGTG_DEV_MODE", value)
    assert Config.from_env().dev_mode is False


def test_dev_floor_is_below_the_production_floor():
    assert DEV_MIN_POLL_INTERVAL_SECONDS < MIN_POLL_INTERVAL_SECONDS
