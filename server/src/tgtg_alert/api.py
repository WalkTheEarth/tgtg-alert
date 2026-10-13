"""HTTP API for the phone app.

Scope is deliberately small: manage watches, register a push token, read alert
history, and run a one-off live search so the app can help you *find* a store
to watch rather than requiring you to type its name exactly.

Auth is a single bearer token, generated at `init` and shared by scanning the
pairing QR. That is the right weight for a box one person owns: it keeps a
stray port-scan from reading your watch list or pushing spam to your phone,
without inventing accounts and sessions for a service with one user.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__, db
from .config import Config
from .matcher import WatchRule, matches
from .tgtg_source import CredentialsMissing, TgtgBlocked, TgtgRateLimited, TgtgSource

log = logging.getLogger(__name__)


# -- schemas -------------------------------------------------------------


class WatchCreate(BaseModel):
    label: str = ""
    store_pattern: str | None = None
    bag_pattern: str | None = None
    # Major units (5.00), not minor. The phone should not have to know that
    # TGTG sends cents.
    max_price: float | None = Field(default=None, ge=0, le=1000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: int = Field(default=10, ge=1, le=100)
    notify_on_increase: bool = False
    enabled: bool = True


class WatchUpdate(BaseModel):
    label: str | None = None
    store_pattern: str | None = None
    bag_pattern: str | None = None
    max_price: float | None = Field(default=None, ge=0, le=1000)
    radius_km: int | None = Field(default=None, ge=1, le=100)
    notify_on_increase: bool | None = None
    enabled: bool | None = None


class DeviceCreate(BaseModel):
    expo_push_token: str = Field(min_length=8)
    platform: str | None = None
    label: str = ""


class PreviewRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: int = Field(default=10, ge=1, le=100)
    query: str | None = None
    limit: int = Field(default=40, ge=1, le=200)


def _watch_row_to_dict(row: Any, *, seen: int = 0, in_stock: int = 0) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "store_pattern": row["store_pattern"],
        "bag_pattern": row["bag_pattern"],
        "max_price": (row["max_price_minor"] / 100) if row["max_price_minor"] is not None else None,
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "radius_km": row["radius_km"],
        "enabled": bool(row["enabled"]),
        "notify_on_increase": bool(row["notify_on_increase"]),
        "baselined": row["baselined_at"] is not None,
        "created_at": row["created_at"],
        "tracked_items": seen,
        "items_in_stock": in_stock,
    }


def _require_token(config: Config):
    def dependency(authorization: str = Header(default="")) -> None:
        scheme, _, token = authorization.partition(" ")
        # compare_digest keeps the check constant-time. Overkill for a LAN box,
        # free to do, and correct if this is ever exposed.
        if scheme.lower() != "bearer" or not token or not secrets.compare_digest(
            token, config.api_token
        ):
            raise HTTPException(status_code=401, detail="invalid or missing API token")

    return dependency


def create_app(config: Config) -> FastAPI:
    app = FastAPI(
        title="TGTG Alert",
        version=__version__,
        description="Self-hosted Too Good To Go availability watcher.",
    )
    auth = _require_token(config)

    # -- health ----------------------------------------------------------

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/status", dependencies=[Depends(auth)])
    def status() -> dict:
        with db.closing_connection(config.db_path) as conn:
            creds = conn.execute("SELECT email FROM tgtg_credentials WHERE id = 1").fetchone()
            watch_count = conn.execute("SELECT COUNT(*) c FROM watches").fetchone()["c"]
            device_count = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
            last = conn.execute(
                "SELECT * FROM poll_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            recent_blocks = conn.execute(
                "SELECT COUNT(*) c FROM poll_runs WHERE blocked = 1 "
                "AND started_at > datetime('now', '-1 day')"
            ).fetchone()["c"]

        return {
            "version": __version__,
            "account": creds["email"] if creds else None,
            "logged_in": creds is not None,
            "poll_interval_seconds": config.poll_interval,
            "watches": watch_count,
            "devices": device_count,
            "last_run": (
                {
                    "at": last["finished_at"],
                    "items_seen": last["items_seen"],
                    "matched": last["matched"],
                    "alerts": last["alerts"],
                    "errors": last["errors"],
                    "blocked": bool(last["blocked"]),
                    "note": last["note"],
                }
                if last
                else None
            ),
            # Surfaced prominently: a silently blocked tracker is the failure
            # this whole design exists to make visible.
            "blocked_in_last_24h": recent_blocks,
        }

    # -- watches ---------------------------------------------------------

    @app.get("/api/watches", dependencies=[Depends(auth)])
    def list_watches() -> list[dict]:
        with db.closing_connection(config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT w.*,
                       (SELECT COUNT(*) FROM observations o WHERE o.watch_id = w.id) AS seen,
                       (SELECT COUNT(*) FROM observations o
                         WHERE o.watch_id = w.id AND o.last_quantity > 0)        AS in_stock
                  FROM watches w ORDER BY w.id
                """
            ).fetchall()
        return [
            _watch_row_to_dict(r, seen=r["seen"], in_stock=r["in_stock"]) for r in rows
        ]

    @app.post("/api/watches", status_code=201, dependencies=[Depends(auth)])
    def create_watch(payload: WatchCreate) -> dict:
        max_minor = int(round(payload.max_price * 100)) if payload.max_price is not None else None
        with db.transaction(config.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO watches
                    (label, store_pattern, bag_pattern, max_price_minor,
                     latitude, longitude, radius_km, notify_on_increase, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.label, payload.store_pattern, payload.bag_pattern, max_minor,
                    payload.latitude, payload.longitude, payload.radius_km,
                    1 if payload.notify_on_increase else 0, 1 if payload.enabled else 0,
                ),
            )
            watch_id = cur.lastrowid
            row = conn.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
        return _watch_row_to_dict(row)

    @app.patch("/api/watches/{watch_id}", dependencies=[Depends(auth)])
    def update_watch(watch_id: int, payload: WatchUpdate) -> dict:
        fields: list[str] = []
        values: list[Any] = []

        data = payload.model_dump(exclude_unset=True)
        for key, column in (
            ("label", "label"),
            ("store_pattern", "store_pattern"),
            ("bag_pattern", "bag_pattern"),
            ("radius_km", "radius_km"),
        ):
            if key in data:
                fields.append(f"{column} = ?")
                values.append(data[key])

        if "max_price" in data:
            fields.append("max_price_minor = ?")
            values.append(int(round(data["max_price"] * 100)) if data["max_price"] is not None else None)
        if "notify_on_increase" in data:
            fields.append("notify_on_increase = ?")
            values.append(1 if data["notify_on_increase"] else 0)
        if "enabled" in data:
            fields.append("enabled = ?")
            values.append(1 if data["enabled"] else 0)

        if not fields:
            raise HTTPException(status_code=400, detail="no fields to update")

        values.append(watch_id)
        with db.transaction(config.db_path) as conn:
            cur = conn.execute(f"UPDATE watches SET {', '.join(fields)} WHERE id = ?", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="watch not found")
            row = conn.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
        return _watch_row_to_dict(row)

    @app.delete("/api/watches/{watch_id}", status_code=204, dependencies=[Depends(auth)])
    def delete_watch(watch_id: int) -> None:
        with db.transaction(config.db_path) as conn:
            cur = conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="watch not found")

    @app.post("/api/watches/{watch_id}/rebaseline", dependencies=[Depends(auth)])
    def rebaseline(watch_id: int) -> dict:
        """Forget current stock so the next poll re-surveys without alerting.

        Use after a long outage: everything looks 'new' if we compare against a
        week-old picture, and the user would get a burst of stale news.
        """
        with db.transaction(config.db_path) as conn:
            cur = conn.execute(
                "UPDATE watches SET baselined_at = NULL WHERE id = ?", (watch_id,)
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="watch not found")
            conn.execute("DELETE FROM observations WHERE watch_id = ?", (watch_id,))
        return {"ok": True, "rebaselined": watch_id}

    # -- devices ---------------------------------------------------------

    @app.get("/api/devices", dependencies=[Depends(auth)])
    def list_devices() -> list[dict]:
        with db.closing_connection(config.db_path) as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        return [
            {
                "id": r["id"],
                "platform": r["platform"],
                "label": r["label"],
                "created_at": r["created_at"],
                "last_seen_at": r["last_seen_at"],
                # The token itself is a capability -- never echo it back.
                "token_hint": (r["expo_push_token"][:14] + "...") if r["expo_push_token"] else "",
            }
            for r in rows
        ]

    @app.post("/api/devices", status_code=201, dependencies=[Depends(auth)])
    def register_device(payload: DeviceCreate) -> dict:
        with db.transaction(config.db_path) as conn:
            conn.execute(
                """
                INSERT INTO devices (expo_push_token, platform, label)
                VALUES (?, ?, ?)
                ON CONFLICT(expo_push_token) DO UPDATE SET
                    platform     = excluded.platform,
                    label        = excluded.label,
                    last_seen_at = datetime('now')
                """,
                (payload.expo_push_token, payload.platform, payload.label),
            )
            row = conn.execute(
                "SELECT * FROM devices WHERE expo_push_token = ?", (payload.expo_push_token,)
            ).fetchone()
        return {"id": row["id"], "platform": row["platform"], "label": row["label"]}

    @app.delete("/api/devices/{device_id}", status_code=204, dependencies=[Depends(auth)])
    def delete_device(device_id: int) -> None:
        with db.transaction(config.db_path) as conn:
            cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="device not found")

    # -- alerts & history ------------------------------------------------

    @app.get("/api/alerts", dependencies=[Depends(auth)])
    def list_alerts(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
        with db.closing_connection(config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT a.*, w.label AS watch_label
                  FROM alerts a LEFT JOIN watches w ON w.id = a.watch_id
                 ORDER BY a.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "watch_id": r["watch_id"],
                "watch_label": r["watch_label"],
                "item_id": r["item_id"],
                "title": r["title"],
                "body": r["body"],
                "devices_ok": r["devices_ok"],
                "devices_err": r["devices_err"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    @app.get("/api/runs", dependencies=[Depends(auth)])
    def list_runs(limit: int = Query(default=20, ge=1, le=200)) -> list[dict]:
        with db.closing_connection(config.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM poll_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- live preview ----------------------------------------------------

    @app.post("/api/preview", dependencies=[Depends(auth)])
    def preview(payload: PreviewRequest) -> dict:
        """Search TGTG live, so the app can suggest stores to watch.

        This spends a real API call, so the app should treat it as an explicit
        user action (pull-to-refresh), not something it does on a timer.
        """
        with db.closing_connection(config.db_path) as conn:
            creds = conn.execute("SELECT * FROM tgtg_credentials WHERE id = 1").fetchone()
        if not creds:
            raise HTTPException(status_code=409, detail="not logged in to Too Good To Go")

        source = TgtgSource(
            dict(creds),
            language=config.default_language,
            timeout=config.request_timeout,
            user_agent=config.user_agent,
        )
        try:
            items = source.fetch_items(payload.latitude, payload.longitude, payload.radius_km)
        except TgtgBlocked as exc:
            raise HTTPException(
                status_code=429,
                detail=f"Too Good To Go is temporarily blocking this server "
                       f"(retry in ~{round(exc.retry_after / 60)} min).",
            ) from exc
        except TgtgRateLimited as exc:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limited by Too Good To Go (retry in ~{round(exc.retry_after / 60)} min).",
            ) from exc
        except CredentialsMissing as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        if payload.query:
            import re

            needle = re.sub(r"\s+", " ", payload.query).strip().casefold()
            items = [
                i
                for i in items
                if needle in re.sub(r"\s+", " ", f"{i.store_name} {i.display_name}").casefold()
            ]

        items = sorted(items, key=lambda i: (i.distance_m if i.distance_m is not None else 1e9))
        return {
            "count": len(items),
            "items": [
                {
                    "item_id": i.item_id,
                    "store_name": i.store_name,
                    "display_name": i.display_name,
                    "quantity": i.quantity,
                    "price": i.price_display,
                    "currency": i.currency,
                    "distance_m": i.distance_m,
                    "pickup_end": i.pickup_end,
                    "category": i.item_category,
                }
                for i in items[: payload.limit]
            ],
        }

    # -- test push -------------------------------------------------------

    @app.post("/api/test-notify", dependencies=[Depends(auth)])
    def test_notify() -> dict:
        from .notify import ExpoNotifier

        with db.closing_connection(config.db_path) as conn:
            tokens = [r["expo_push_token"] for r in conn.execute("SELECT expo_push_token FROM devices")]
        if not tokens:
            raise HTTPException(status_code=409, detail="no paired devices")

        result = ExpoNotifier(config.expo_access_token).send(
            tokens, "Test alert", "If you can see this, alerts are wired up correctly."
        )
        if result.dead_tokens:
            with db.transaction(config.db_path) as conn:
                conn.executemany(
                    "DELETE FROM devices WHERE expo_push_token = ?",
                    [(t,) for t in result.dead_tokens],
                )
        return {"sent": result.sent, "errors": result.errors, "messages": result.error_messages}

    @app.post("/api/preview-watch", dependencies=[Depends(auth)])
    def preview_watch(watch_id: int = Body(..., embed=True)) -> dict:
        """Report what the stored rules would match without alerting."""
        with db.closing_connection(config.db_path) as conn:
            row = conn.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
            creds = conn.execute("SELECT * FROM tgtg_credentials WHERE id = 1").fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="watch not found")
        if not creds:
            raise HTTPException(status_code=409, detail="not logged in to Too Good To Go")

        rule = WatchRule(
            id=row["id"],
            store_pattern=row["store_pattern"],
            bag_pattern=row["bag_pattern"],
            max_price_minor=row["max_price_minor"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            radius_km=row["radius_km"],
        )
        source = TgtgSource(
            dict(creds),
            language=config.default_language,
            timeout=config.request_timeout,
            user_agent=config.user_agent,
        )
        try:
            items = source.fetch_items(row["latitude"], row["longitude"], row["radius_km"])
        except (TgtgBlocked, TgtgRateLimited) as exc:
            raise HTTPException(status_code=429, detail="Too Good To Go is rate limiting this server.") from exc

        matched = [i for i in items if matches(rule, i)]
        return {
            "matched": len(matched),
            "of_total": len(items),
            "items": [
                {
                    "item_id": i.item_id,
                    "store_name": i.store_name,
                    "display_name": i.display_name,
                    "quantity": i.quantity,
                    "price": i.price_display,
                }
                for i in matched[:50]
            ],
        }

    return app
