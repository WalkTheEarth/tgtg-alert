"""Push delivery via the Expo Push service.

Why Expo rather than talking to APNs and FCM directly: it is one integration
and one credential set instead of two, it is free, and it is a *proxy* -- the
app can call `getDevicePushTokenAsync()` and hand us native APNs/FCM tokens
later without any change here.

The settings below are not decoration. A stock alert is worthless if it arrives
late or silently:

* `priority: "high"` maps to FCM high priority and APNs `apns-priority: 10`.
  Only FCM high priority wakes a device in Doze -- normal priority is deferred
  to a maintenance window, which for a bag that sells out in minutes means
  never.
* `interruptionLevel: "time-sensitive"` breaks through iOS Focus modes.
* A short `ttl` stops a stale "in stock!" from landing hours later, long after
  the bag is gone.
* `collapseId` per watch means a restock storm replaces itself rather than
  stacking twenty banners.

Delivery is best-effort at every hop. Expo targets "at-least-once", APNs keeps
only one pending notification per app, and tokens go stale when an app is
uninstalled -- hence `DeviceNotRegistered` handling, which prunes the token so
we stop burning quota on a phone that no longer exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"

# Expo accepts up to 100 messages per request.
BATCH_SIZE = 100
# 15 minutes: long enough to survive a brief connectivity gap, short enough
# that nobody is told about a bag that sold out an hour ago.
ALERT_TTL_SECONDS = 900

# Android channel id. Importance is fixed when a channel is first created and
# cannot be raised afterwards -- only a *new* channel id can do that -- so this
# id is versioned. Bump the suffix rather than changing the importance.
ANDROID_CHANNEL_ID = "tgtg-alerts-v1"


@dataclass
class PushResult:
    sent: int = 0
    errors: int = 0
    dead_tokens: list[str] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.errors == 0


class ExpoNotifier:
    def __init__(self, access_token: str | None = None, timeout: float = 15.0):
        self.access_token = access_token
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json",
        }
        if self.access_token:
            # Optional, but recommended: without it anyone holding a push token
            # can post to it through Expo's service.
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _message(
        self,
        token: str,
        title: str,
        body: str,
        *,
        collapse_key: str | None,
        data: dict | None,
    ) -> dict:
        return {
            "to": token,
            "title": title,
            "body": body,
            "sound": "default",
            "priority": "high",
            "ttl": ALERT_TTL_SECONDS,
            "interruptionLevel": "time-sensitive",
            "channelId": ANDROID_CHANNEL_ID,
            "collapseId": collapse_key,
            "data": data or {},
        }

    def send(
        self,
        tokens: list[str],
        title: str,
        body: str,
        *,
        collapse_key: str | None = None,
        data: dict | None = None,
    ) -> PushResult:
        result = PushResult()
        if not tokens:
            return result

        for start in range(0, len(tokens), BATCH_SIZE):
            chunk = tokens[start : start + BATCH_SIZE]
            messages = [
                self._message(t, title, body, collapse_key=collapse_key, data=data)
                for t in chunk
            ]
            try:
                response = self.session.post(
                    EXPO_PUSH_URL,
                    json=messages,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                log.error("expo push request failed: %s", exc)
                result.errors += len(chunk)
                result.error_messages.append(str(exc))
                continue

            if response.status_code >= 400:
                log.error("expo push HTTP %s: %s", response.status_code, response.text[:300])
                result.errors += len(chunk)
                result.error_messages.append(f"HTTP {response.status_code}")
                continue

            self._tally(response.json(), chunk, result)

        return result

    def _tally(self, payload: dict, chunk: list[str], result: PushResult) -> None:
        """Fold Expo's per-message tickets into the running result."""
        tickets = payload.get("data")
        if not isinstance(tickets, list):
            result.sent += len(chunk)
            return

        for token, ticket in zip(chunk, tickets):
            if not isinstance(ticket, dict):
                result.sent += 1
                continue
            if ticket.get("status") == "error":
                code = (ticket.get("details") or {}).get("error")
                message = ticket.get("message", "unknown")
                if code == "DeviceNotRegistered":
                    # The app was uninstalled or the token rotated. Stop sending.
                    result.dead_tokens.append(token)
                    log.info("pruning dead push token")
                else:
                    result.errors += 1
                    result.error_messages.append(f"{code}: {message}")
                    log.warning("push ticket error %s: %s", code, message)
            else:
                result.sent += 1

    def check_receipts(self, receipt_ids: list[str]) -> PushResult:
        """Look up delivery receipts for previously accepted tickets.

        A ticket only proves Expo accepted the message. Receipts are where
        APNs/FCM-level failures surface, so this is worth calling for alerts
        that matter -- but it is best-effort and deliberately non-fatal.
        """
        result = PushResult()
        if not receipt_ids:
            return result

        for start in range(0, len(receipt_ids), 1000):
            chunk = receipt_ids[start : start + 1000]
            try:
                response = self.session.post(
                    EXPO_RECEIPTS_URL,
                    json={"ids": chunk},
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                if response.status_code >= 400:
                    continue
                for receipt in (response.json().get("data") or {}).values():
                    if not isinstance(receipt, dict):
                        continue
                    if receipt.get("status") == "error":
                        code = (receipt.get("details") or {}).get("error")
                        if code == "DeviceNotRegistered":
                            result.dead_tokens.append(receipt.get("to", ""))
                        else:
                            result.errors += 1
                            result.error_messages.append(str(code))
                    else:
                        result.sent += 1
            except (requests.RequestException, ValueError) as exc:
                log.warning("receipt lookup failed: %s", exc)

        return result


class WebhookNotifier:
    """POSTs a small JSON body to a user-supplied URL.

    Exists so a self-hoster can route alerts somewhere useful without a phone
    in the loop -- ntfy, a Discord/Slack webhook, Home Assistant, or a shell
    script. Also the easiest way to verify the whole pipeline end to end.
    """

    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url
        self.timeout = timeout

    def send(
        self,
        tokens: list[str],
        title: str,
        body: str,
        *,
        collapse_key: str | None = None,
        data: dict | None = None,
    ) -> PushResult:
        result = PushResult()
        try:
            response = requests.post(
                self.url,
                json={"title": title, "body": body, "data": data or {}},
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                result.errors = 1
                result.error_messages.append(f"HTTP {response.status_code}")
            else:
                result.sent = 1
        except requests.RequestException as exc:
            result.errors = 1
            result.error_messages.append(str(exc))
        return result
