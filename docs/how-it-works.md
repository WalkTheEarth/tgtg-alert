# How it works

Why the architecture is what it is, and exactly when the server decides to wake
you up.

## Why a server is unavoidable

The obvious design — an app that polls in the background and buzzes you — does
not work, and this is not a limitation of any particular framework. Both mobile
operating systems forbid it, deliberately, because a background process polling
every few minutes is exactly what they exist to prevent.

**iOS** has no guaranteed background refresh interval at all. `BGAppRefreshTask`
documents no frequency contract; the system decides when to run your task based
on battery, thermal state, and how often the user opens the app. Apple's own
developer support, answering someone asking for sub-30-second refresh:

> "There is no way to get resumed (or relaunched) in the background at that
> rate."

In practice a frequently-used app gets a few wake-ups a day, at times the system
chooses. `BGContinuedProcessingTask` (iOS 26+) does not help — it requires the
task to be submitted *from the foreground* and shows a Live Activity with a
cancel button, so it cannot wake a backgrounded app on a cadence.

**Android** is less hostile but still unusable for this. `WorkManager` enforces a
hard fifteen-minute floor on periodic work, which is a framework constant, not a
setting. Worse, Doze and App Standby restrict background networking based on how
often the app is used — and a stock-alert app is by definition one you rarely
open. In the Rare and Restricted buckets, **background network access is disabled
outright**.

Bags appear at unpredictable times and often sell out within minutes. A poller
with a fifteen-minute floor that the OS may skip entirely would miss most of
them.

So something has to poll on a real schedule, from somewhere that is always on.
That is the whole reason this project has a server half.

> The one exception: **push notifications still work fine.** The OS restrictions
> are on *polling*, not on receiving. That asymmetry is what makes the
> architecture work — do the polling somewhere it is allowed, and push the result.

## The shape of it

```
                        ┌─────────────────────────────────┐
                        │   your machine, Pi, or NAS      │
                        │                                 │
   TGTG API ◄───────────┤  poller ──▶ matcher ──▶ notifier│
  (unofficial)          │    │                    │       │
                        │    └──▶ SQLite           │       │
                        │                         │       │
                        │  HTTP API ◄─────────┐   │       │
                        └─────────────────────┼───┼───────┘
                                              │   │
                                 pairing QR   │   │  push
                                              │   ▼
                                       ┌──────┴────────┐
                                       │   phone app   │
                                       │  iOS/Android  │
                                       └───────────────┘
```

The phone never talks to Too Good To Go. It only talks to your server.

## The poll loop

Every `TGTG_POLL_INTERVAL` seconds (default 600 — ten minutes), `Poller.run_once()`
does this:

1. **Load credentials** from SQLite, refreshing the access token if it is older
   than four hours.
2. **Load enabled watches**, and group them by location (see below).
3. **Fetch** the items near each location bucket.
4. **Match** each item against each watch's rules.
5. **Decide** whether each match warrants a notification.
6. **Record** the outcome, and send any alerts.

A failed bucket does not abort the pass. A *blocked* pass aborts everything
immediately, because retrying into a DataDome refusal makes it worse.

### Location bucketing

Too Good To Go rate-limits per account, not per request. Ten watches in one city
must not cost ten API calls, or you will get blocked for being greedy.

So watches are grouped by coordinate, rounded to two decimal places (~1.1 km),
and each bucket is fetched **once** at the widest radius any watch in it asked
for. Each watch then narrows the results using the per-store distance the API
already returns.

Ten watches in central London: one API call. Ten watches scattered across a
country: ten calls, unavoidably.

### Absence means sold out

The poller asks for `with_stock_only=False`, because the whole alert mechanism is
the 0 → >0 transition and you cannot see a zero you never asked for.

But it is not certain that the API returns sold-out items even when asked. If it
does not, a bag simply vanishes from the response when it sells out and
reappears later — and a detector comparing only *present* quantities would never
observe the zero, and so would never fire.

So: **on a complete, successful fetch, any previously-seen item that is now
missing is recorded as quantity 0.** That makes the transition detectable either
way.

The "complete and successful" qualifier is load-bearing. Zeroing on a partial or
failed fetch would manufacture a wave of fake restocks on the next good poll.

### Token refresh

The access token is treated as valid for four hours, matching the official app.
This is enforced by the client library, and there is a subtlety: the library
skips a refresh only if it knows when the last one happened. A freshly
constructed client does not, so it refreshes on **every single call** — doubling
request volume against an API that blocks for exactly that kind of behaviour.

The poller therefore persists `last_time_token_refreshed` alongside the tokens
and restores it on startup. Refresh tokens rotate on every refresh, so they are
written back after each pass.

## When it alerts you

This is the part worth getting right. The naive version either spams you or
stays silent.

| Situation | Behaviour | Why |
|---|---|---|
| **First ever poll** | Silent | Otherwise setup fires a notification for every bag already in stock. This is the *baseline*. |
| **Sold out → available** (`0 → >0`) | **Alerts** | The main event. |
| **Never-seen bag appears, after baseline** | **Alerts** | A genuinely new listing — the other half of "tell me when this shows up". |
| **Never-seen bag appears, before baseline** | Silent | Part of the initial survey. |
| **Still available** (`4 → 4`) | Quiet | A bag sitting there all afternoon is not news. Re-alerting is how you get muted. |
| **More available** (`2 → 6`) | Quiet by default | Opt in per watch with `--notify-on-increase`. |
| **Available → sold out** | Quiet, but remembered | This is what makes the next `0 → >0` detectable. |

### The baseline, and why you sometimes need to reset it

A watch starts unbaselined. Its first successful poll records everything and
alerts on nothing. After that, anything new or restocked alerts.

The problem case is **downtime**. If the server is off for a week, everything it
sees on restart looks new, and you get a burst of stale news about bags that were
available all along. If that happens, re-baseline:

```bash
tgtg-alert watch update 1 --rebaseline
```

That clears the stored picture and starts fresh, so the next poll is a silent
survey again.

### Matching rules

An item must satisfy **every** constraint a watch sets. Each is optional:

| Field | Behaviour |
|---|---|
| `store_pattern` | Case-insensitive substring of the store name. Whitespace is collapsed, so `"blank  street"` matches `"Blank Street"`. |
| `bag_pattern` | Case-insensitive substring of the bag name — `"Magic Bag"`, `"Bakery Box"`. |
| `max_price_minor` | Alerts only at or below this price. |
| `radius_km` | Only bags within this distance of the centre point. |
| `notify_on_increase` | Off by default. See the table above. |

A watch with no `store_pattern` and no `bag_pattern` matches everything in
radius — the intentional "any bag near me" firehose.

One deliberate edge case: an item whose **price cannot be read** passes a price
ceiling rather than failing it. Silently dropping unparseable items would hide
real matches, and a missing alert is worse than a cheap bag slipping through.

## When Too Good To Go pushes back

The expected failure is **HTTP 403 from DataDome**, not a 429 rate limit. That
distinction drives the whole design: a 403 is a verdict on your fingerprint, not
a quota, so retrying makes it worse.

| Response | Meaning | Reaction |
|---|---|---|
| **403** | DataDome refused you. | Back off **1h, then 2h, 4h, capped at 6h**. Abort the pass — no point trying other buckets. |
| **429** | A quota. | Back off 60s, 120s, 240s, capped at 30 min. |
| **Anything else** | Usually transient. | Log it, skip that bucket, continue. |

Two details that matter:

- **No retry amplification.** The client library already retries a 403 once with
  a fresh cookie, costing two request pairs per block. Adding our own retry on
  top is how a temporary block becomes a permanent one.
- **Backoff survives across polls.** A block that is forgotten on the next pass
  is not a backoff at all.

Blocks clear on their own. Alerts resume automatically — nothing is broken, and
restarting the service does not help.

## Delivery

Alerts go to the Expo Push service, which fans out to APNs and FCM. The settings
are chosen so the notification actually interrupts you:

| Setting | Value | Why |
|---|---|---|
| `priority` | `high` | Maps to FCM high priority and APNs `apns-priority: 10`. Only FCM high priority wakes a device in Doze — normal priority is deferred to a maintenance window, which for a bag that sells out in minutes means never. |
| `interruptionLevel` | `time-sensitive` | Breaks through iOS Focus modes. Does not need Apple's separate critical-alert entitlement. |
| `ttl` | 900s | Stops a stale "in stock!" arriving long after the bag is gone. |
| `collapseId` | per watch | A restock burst replaces itself on the lock screen instead of stacking twenty banners. |
| Android channel | `IMPORTANCE_MAX` | A silent tray notification is indistinguishable from no alert. |

**The Android channel id is versioned** (`tgtg-alerts-v1`) and that is not
decoration. Channel importance is fixed at creation and can never be raised
afterwards — only a *new* channel id can do that. Shipping a low-importance
channel and "fixing" it later would leave every existing install silently
broken.

Dead tokens are pruned automatically when Expo reports `DeviceNotRegistered`
(the app was uninstalled), so the server stops burning sends on a phone that no
longer exists.

### Webhook delivery

Set `TGTG_WEBHOOK_URL` and every alert also POSTs a small JSON body there. Useful
for `ntfy`, Discord, Slack, Home Assistant, or a shell script — and it is the
easiest way to verify the pipeline end to end without a phone.

See [Configuration](configuration.md#tgtg_webhook_url).

## Data model

Four tables, all in `data/tgtg_alert.db`:

| Table | Holds |
|---|---|
| `tgtg_credentials` | One row: your session. Access token, refresh token, cookie, UA, last-refresh time. |
| `watches` | Your rules, plus `baselined_at` and the increase-notification flag. |
| `observations` | Per watch, per item: last seen quantity and price. **This is the memory that makes transition detection possible.** |
| `alerts` | A log of everything sent, with delivery counts. Powers the app's Activity tab. |
| `poll_runs` | One row per pass. Powers the status screen — including `blocked`, which is how you find out the tracker has been silently refused for six hours. |
| `devices` | Paired phones and their Expo push tokens. |
| `page_cache` | Schema exists for caching pages per location bucket. |

## Where to look next

- [Configuration](configuration.md) — tuning polling frequency and notifications.
- [Troubleshooting](troubleshooting.md) — when it stops working.
- [Development](development.md) — the code layout, if you want to change it.
