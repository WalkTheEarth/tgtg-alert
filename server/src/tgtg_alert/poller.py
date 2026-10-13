"""The polling engine: fetch, match, decide, alert, remember.

Runs one pass synchronously (`run_once`) so it can be unit-tested and invoked
from cron, and a cancellable loop (`run_forever`) for the long-running service.

Two things here are worth understanding before changing them.

**Location bucketing.** TGTG rate-limits per account, not per request, so ten
watches in one city must not cost ten API calls. Watches are grouped by a
rounded coordinate, one fetch is made per bucket at the bucket's widest radius,
and each watch then filters by its own radius using the distance the API
already returns per store.

**Absence means zero.** It is not certain that `get_items` returns sold-out
items even with `with_stock_only=False`. If it does not, a bag would simply
disappear from the response when it sells out, and reappear later -- and a
detector that only compared present quantities would never observe the 0 and
would therefore never fire. So on a *complete, successful* fetch, any
previously-seen item that is now missing is treated as quantity 0. That makes
0 -> >0 detection work either way. The "complete and successful" qualifier
matters: zeroing on a partial or failed fetch would manufacture fake restocks
on the next good poll.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import db
from .config import BACKOFF_ON_BLOCK_SECONDS, Config
from .matcher import WatchRule, build_notification, decide, matches
from .notify import ExpoNotifier, WebhookNotifier
from .tgtg_source import (
    CredentialsMissing,
    Item,
    TgtgBlocked,
    TgtgRateLimited,
    TgtgSource,
)

log = logging.getLogger(__name__)

# Coordinates are rounded to 2dp (~1.1km) to decide which watches share a fetch.
BUCKET_PRECISION = 2


@dataclass
class PollStats:
    watches: int = 0
    buckets: int = 0
    items_seen: int = 0
    matched: int = 0
    alerts: int = 0
    errors: int = 0
    rate_limited: bool = False
    # DataDome refusal. Distinguished from a rate limit because the response is
    # different: an hour-plus of silence, not a short pause.
    blocked: bool = False
    blocked_for: float = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def bucket_key(latitude: float, longitude: float) -> str:
    return f"{round(latitude, BUCKET_PRECISION)}:{round(longitude, BUCKET_PRECISION)}"


class Poller:
    def __init__(self, config: Config, webhook_url: str | None = None):
        self.config = config
        self.webhook_url = webhook_url
        self._stop = threading.Event()

    # -- data access ------------------------------------------------------

    def _load_credentials(self) -> dict | None:
        with db.closing_connection(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM tgtg_credentials WHERE id = 1").fetchone()
        return dict(row) if row else None

    def _save_credentials(self, creds: dict) -> None:
        with db.transaction(self.config.db_path) as conn:
            conn.execute(
                """
                UPDATE tgtg_credentials
                   SET access_token = ?, refresh_token = ?, cookie = ?,
                       last_time_token_refreshed = ?, updated_at = datetime('now')
                 WHERE id = 1
                """,
                (
                    creds.get("access_token"),
                    creds.get("refresh_token"),
                    creds.get("cookie"),
                    creds.get("last_time_token_refreshed"),
                ),
            )

    def _load_watches(self) -> list[WatchRule]:
        with db.closing_connection(self.config.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM watches WHERE enabled = 1 ORDER BY id"
            ).fetchall()
        return [
            WatchRule(
                id=r["id"],
                store_pattern=r["store_pattern"],
                bag_pattern=r["bag_pattern"],
                max_price_minor=r["max_price_minor"],
                latitude=r["latitude"],
                longitude=r["longitude"],
                radius_km=r["radius_km"],
                enabled=bool(r["enabled"]),
                baselined=r["baselined_at"] is not None,
                notify_on_increase=bool(r["notify_on_increase"]),
            )
            for r in rows
        ]

    def _previous_quantities(self, watch_id: int) -> dict[str, int]:
        with db.closing_connection(self.config.db_path) as conn:
            rows = conn.execute(
                "SELECT item_id, last_quantity FROM observations WHERE watch_id = ?",
                (watch_id,),
            ).fetchall()
        return {r["item_id"]: r["last_quantity"] for r in rows}

    def _device_tokens(self) -> list[str]:
        with db.closing_connection(self.config.db_path) as conn:
            rows = conn.execute("SELECT expo_push_token FROM devices").fetchall()
        return [r["expo_push_token"] for r in rows]

    def _prune_tokens(self, tokens: list[str]) -> None:
        tokens = [t for t in tokens if t]
        if not tokens:
            return
        with db.transaction(self.config.db_path) as conn:
            conn.executemany(
                "DELETE FROM devices WHERE expo_push_token = ?", [(t,) for t in tokens]
            )
        log.info("pruned %d dead push token(s)", len(tokens))

    def _record_run(self, stats: PollStats, note: str | None = None) -> None:
        with db.transaction(self.config.db_path) as conn:
            conn.execute(
                """
                INSERT INTO poll_runs
                    (finished_at, watches, buckets, items_seen, matched,
                     alerts, errors, blocked, note)
                VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stats.watches, stats.buckets, stats.items_seen, stats.matched,
                    stats.alerts, stats.errors, 1 if stats.blocked else 0, note,
                ),
            )

    def _record_alert(self, watch_id: int | None, item_id: str | None, title: str,
                      body: str, sent: int, errors: int, error: str | None) -> None:
        with db.transaction(self.config.db_path) as conn:
            conn.execute(
                """
                INSERT INTO alerts (watch_id, item_id, title, body, devices_ok, devices_err, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (watch_id, item_id, title, body, sent, errors, error),
            )

    # -- observation bookkeeping -----------------------------------------

    def _upsert_observation(self, watch_id: int, item: Item, alerted: bool) -> None:
        with db.transaction(self.config.db_path) as conn:
            conn.execute(
                """
                INSERT INTO observations
                    (watch_id, item_id, store_id, store_name, display_name,
                     last_quantity, last_price_minor, last_seen_at, last_alerted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'),
                        CASE WHEN ? THEN datetime('now') ELSE NULL END)
                ON CONFLICT(watch_id, item_id) DO UPDATE SET
                    store_id         = excluded.store_id,
                    store_name       = excluded.store_name,
                    display_name     = excluded.display_name,
                    last_quantity    = excluded.last_quantity,
                    last_price_minor = excluded.last_price_minor,
                    last_seen_at     = datetime('now'),
                    last_alerted_at  = CASE WHEN ? THEN datetime('now')
                                            ELSE observations.last_alerted_at END
                """,
                (
                    watch_id,
                    item.item_id,
                    item.store_id,
                    item.store_name,
                    item.display_name,
                    item.quantity,
                    item.price_minor,
                    1 if alerted else 0,
                    1 if alerted else 0,
                ),
            )

    def _zero_missing(self, watch_id: int, seen_item_ids: set[str]) -> int:
        """Mark previously-seen items that vanished from the response as 0.

        See the module docstring: this is what makes restock detection work if
        TGTG omits sold-out items. Only ever called after a complete fetch.
        """
        previous = self._previous_quantities(watch_id)
        vanished = [i for i, qty in previous.items() if i not in seen_item_ids and qty > 0]
        if not vanished:
            return 0
        with db.transaction(self.config.db_path) as conn:
            conn.executemany(
                "UPDATE observations SET last_quantity = 0, last_seen_at = datetime('now') "
                "WHERE watch_id = ? AND item_id = ?",
                [(watch_id, i) for i in vanished],
            )
        return len(vanished)

    def _mark_baselined(self, watch_id: int) -> None:
        with db.transaction(self.config.db_path) as conn:
            conn.execute(
                "UPDATE watches SET baselined_at = datetime('now') "
                "WHERE id = ? AND baselined_at IS NULL",
                (watch_id,),
            )

    # -- delivery ---------------------------------------------------------

    def _dispatch(self, title: str, body: str, watch: WatchRule, item: Item) -> tuple[int, int, str | None]:
        tokens = self._device_tokens()
        notifier = ExpoNotifier(
            access_token=self.config.expo_access_token, timeout=self.config.request_timeout
        )
        sent = errors = 0
        messages: list[str] = []

        if tokens:
            result = notifier.send(
                tokens,
                title,
                body,
                # One collapse key per watch: a burst of restocks replaces
                # itself on the lock screen instead of stacking up.
                collapse_key=f"watch-{watch.id}",
                data={"watchId": watch.id, "itemId": item.item_id, "storeName": item.store_name},
            )
            sent += result.sent
            errors += result.errors
            messages.extend(result.error_messages)
            if result.dead_tokens:
                self._prune_tokens(result.dead_tokens)

        if self.webhook_url:
            hook = WebhookNotifier(self.webhook_url, timeout=self.config.request_timeout)
            result = hook.send(
                [],
                title,
                body,
                collapse_key=f"watch-{watch.id}",
                data={"watchId": watch.id, "itemId": item.item_id},
            )
            sent += result.sent
            errors += result.errors
            messages.extend(result.error_messages)

        if not tokens and not self.webhook_url:
            log.warning("no devices paired and no webhook configured; alert dropped")
            messages.append("no delivery target configured")

        return sent, errors, ("; ".join(messages) if messages else None)

    # -- the pass ---------------------------------------------------------

    def run_once(self, dry_run: bool = False) -> PollStats:
        stats = PollStats()

        credentials = self._load_credentials()
        if not credentials:
            log.error("no TGTG credentials stored -- run `tgtg-alert login` first")
            raise CredentialsMissing("run `tgtg-alert login` first")

        watches = self._load_watches()
        stats.watches = len(watches)
        if not watches:
            log.info("no enabled watches")
            if not dry_run:
                self._record_run(stats, "no enabled watches")
            return stats

        source = TgtgSource(
            credentials,
            language=self.config.default_language,
            timeout=self.config.request_timeout,
            user_agent=self.config.user_agent,
            block_backoff_seconds=BACKOFF_ON_BLOCK_SECONDS,
        )

        # Group watches that can share one API call.
        buckets: dict[str, list[WatchRule]] = {}
        for watch in watches:
            buckets.setdefault(bucket_key(watch.latitude, watch.longitude), []).append(watch)
        stats.buckets = len(buckets)

        for key, bucket_watches in buckets.items():
            latitude = bucket_watches[0].latitude
            longitude = bucket_watches[0].longitude
            # Fetch at the widest radius anyone in this bucket asked for; each
            # watch narrows it again below.
            radius = max(w.radius_km for w in bucket_watches)

            try:
                items = source.fetch_items(latitude, longitude, radius)
            except (TgtgBlocked, TgtgRateLimited) as exc:
                # Both mean "stop asking". Trying the remaining buckets would
                # only deepen a block that is scoring our fingerprint, so end
                # the pass here and let the backoff run.
                stats.errors += 1
                stats.blocked_for = exc.retry_after
                if isinstance(exc, TgtgBlocked):
                    stats.blocked = True
                    log.error(
                        "pass aborted: TGTG is blocking this host (retry in %d min)",
                        round(exc.retry_after / 60),
                    )
                else:
                    stats.rate_limited = True
                    log.warning(
                        "pass aborted: rate limited (retry in %d min)",
                        round(exc.retry_after / 60),
                    )
                break
            except Exception as exc:  # noqa: BLE001 - one bad bucket must not kill the pass
                stats.errors += 1
                log.error("fetch failed for bucket %s: %s", key, exc)
                continue

            stats.items_seen += len(items)
            log.info("bucket %s: %d items across %d watch(es)", key, len(items), len(bucket_watches))

            for watch in bucket_watches:
                self._apply(watch, items, source, stats, dry_run)

        if not dry_run:
            # Harvest tokens the library may have rotated during the pass.
            self._save_credentials(source.capture_credentials())

        if not dry_run:
            self._record_run(stats)

        log.info(
            "pass complete: %d watch(es), %d item(s), %d match(es), %d alert(s), %d error(s)",
            stats.watches, stats.items_seen, stats.matched, stats.alerts, stats.errors,
        )
        return stats

    def _apply(
        self,
        watch: WatchRule,
        items: list[Item],
        source: TgtgSource,
        stats: PollStats,
        dry_run: bool,
    ) -> None:
        radius_m = watch.radius_km * 1000
        previous = self._previous_quantities(watch.id)

        matched_items = []
        for item in items:
            if not matches(watch, item):
                continue
            # The bucket-wide fetch may be wider than this watch's radius. When
            # the API gives us a distance, honour the tighter bound.
            if item.distance_m is not None and item.distance_m > radius_m:
                continue
            matched_items.append(item)

        stats.matched += len(matched_items)
        seen_ids = {i.item_id for i in matched_items}

        for item in matched_items:
            decision = decide(
                item,
                previous.get(item.item_id),
                baselined=watch.baselined,
                notify_on_increase=watch.notify_on_increase,
            )
            alerted = False

            if decision.should_alert:
                title, body = build_notification(item, decision, watch)
                if dry_run:
                    log.info("[dry-run] would alert: %s | %s", title, body)
                    stats.alerts += 1
                else:
                    sent, errors, error = self._dispatch(title, body, watch, item)
                    stats.alerts += 1
                    stats.errors += 1 if errors else 0
                    alerted = errors == 0
                    self._record_alert(
                        watch.id, item.item_id, title, body, sent, errors, error
                    )
                    log.info("alerted (%s): %s", decision.reason, title)
            elif decision.reason == "baseline":
                log.debug("baseline item %s (%d in stock)", item.item_id, item.quantity)

            if not dry_run:
                self._upsert_observation(watch.id, item, alerted)

        if not dry_run:
            # Absence-as-zero, then seal the baseline for next time.
            vanished = self._zero_missing(watch.id, seen_ids)
            if vanished:
                log.debug("watch %d: %d item(s) left the results -> marked 0", watch.id, vanished)
            if not watch.baselined:
                self._mark_baselined(watch.id)
                watch.baselined = True
                log.info("watch %d baselined (no alerts from the initial survey)", watch.id)

    # -- loop -------------------------------------------------------------

    def run_forever(self) -> None:
        log.info("poller started; interval %ds", self.config.poll_interval)
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                stats = self.run_once()
                elapsed = time.monotonic() - started
                sleep_for = max(self.config.poll_interval - elapsed, 0.0)
                # If TGTG pushed back, sit out longer rather than piling on.
                # A block is a verdict on our fingerprint, so it earns the full
                # escalating backoff; a rate limit is just a quota.
                if stats.rate_limited:
                    sleep_for = max(sleep_for, 60.0)
                if stats.blocked:
                    sleep_for = max(sleep_for, stats.blocked_for)
            except CredentialsMissing:
                log.error("credentials missing; retrying in 60s")
                sleep_for = 60
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                log.exception("poll pass failed: %s", exc)
                sleep_for = min(60, self.config.poll_interval)

            self._stop.wait(sleep_for)

    def stop(self) -> None:
        self._stop.set()
