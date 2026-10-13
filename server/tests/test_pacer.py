"""Tests for call pacing and block backoff.

The backoff is the thing standing between "this tool got my account blocked"
and "this tool pauses politely", so its escalation is worth pinning down.
"""

import time

from tgtg_alert.tgtg_source import Pacer


def test_backoff_escalates_and_caps():
    pacer = Pacer(0.0, block_backoff_seconds=3600.0)
    assert pacer.note_blocked() == 3600        # 1h
    assert pacer.note_blocked() == 7200        # 2h
    assert pacer.note_blocked() == 14400       # 4h
    assert pacer.note_blocked() == 21600       # capped at 6h


def test_rate_limit_backoff_is_shorter_than_a_block():
    """A 429 is a quota; a 403 is a verdict. They should not be conflated."""
    pacer = Pacer(0.0)
    assert pacer.note_rate_limited() == 60
    assert pacer.note_rate_limited() == 120


def test_blocked_state_is_visible():
    pacer = Pacer(0.0, block_backoff_seconds=60.0)
    assert not pacer.is_blocked
    pacer.note_blocked()
    assert pacer.is_blocked
    assert 50 < pacer.blocked_for <= 60


def test_backoff_never_shortens_on_repeat():
    pacer = Pacer(0.0, block_backoff_seconds=600.0)
    first = pacer.note_blocked()
    second = pacer.note_blocked()
    assert second > first


def test_backoff_decays_only_after_it_expires():
    """A tracker that recovers must stay suspicious for a while.

    The classic failure is 'works for 30 minutes, then blocked on the first
    token refresh', so a single good call must not wipe the block history.
    """
    pacer = Pacer(0.0, block_backoff_seconds=0.05)
    pacer.note_blocked()
    assert pacer.consecutive_blocks == 1
    pacer.note_success()  # still inside the block window
    assert pacer.consecutive_blocks == 1

    time.sleep(0.06)
    pacer.note_success()
    assert pacer.consecutive_blocks == 0


def test_success_clears_rate_limit_counter():
    pacer = Pacer(0.0)
    pacer.note_rate_limited()
    pacer.note_success()
    assert pacer.note_rate_limited() == 60  # reset, not escalated


def test_wait_does_not_sleep_when_unblocked_and_unspaced():
    pacer = Pacer(0.0)
    started = time.monotonic()
    pacer.wait()
    assert time.monotonic() - started < 0.5
