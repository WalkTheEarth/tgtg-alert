# Troubleshooting

A diagnosis playbook. Start with the decision tree, then jump to the symptom.

---

## Start here: the decision tree

Almost every problem is one of four things. Answer these in order.

### 1. Is the server talking to Too Good To Go?

```bash
tgtg-alert poll --dry-run
```

| Result | Go to |
|---|---|
| Lists items and matches | ✅ Working. Go to question 2. |
| `403` / mentions DataDome | [Blocked by Too Good To Go](#blocked-403--datadome) |
| `no TGTG credentials stored` | [Not logged in](#not-logged-in) |
| Hangs, then times out | [Network problems](#timeouts-and-connection-failures) |
| Errors mentioning a version or endpoint | [The API moved](#the-api-moved) |

### 2. Is it matching anything?

```bash
tgtg-alert watch list
```

Look at the `TRACKED` column after a few poll cycles.

| Result | Go to |
|---|---|
| `TRACKED` climbing | ✅ Working. Go to question 3. |
| `TRACKED: 0` everywhere | [Nothing matches](#nothing-matches) |
| `(awaiting first poll)` | Normal — wait one interval. |

### 3. Is delivery working?

```bash
tgtg-alert test-notify
```

| Result | Go to |
|---|---|
| Notification arrives | ✅ Everything works. |
| `No paired devices` | [No devices paired](#no-devices-paired) |
| `DeviceNotRegistered` | [Token is dead](#push-token-died) |
| Sent, but nothing arrives | [Notifications not arriving](#notifications-not-arriving) |

### 4. Still stuck?

Check what the server thinks is happening:

```bash
curl -s -H "Authorization: Bearer $TGTG_API_TOKEN" \
  http://localhost:8787/api/status | jq
```

Or open the app's **Settings** tab, which shows the same thing.

---

## Blocked (403 / DataDome)

**The most common failure by a wide margin.** It gets its own section.

### What you will see

```
ERROR tgtg_alert.poller: TGTG refused the request (HTTP 403 / DataDome); backing off 60 min.
  Most likely causes, in order:
    1. A datacenter or VPN IP. ...
    2. A stale User-Agent. ...
    3. Polling too often. ...
```

Or, in the app, a banner on the Settings screen: *"Blocked by Too Good To Go N×
in the last day."*

### What is happening

DataDome, Too Good To Go's bot protection, has decided your client looks
automated. Note that this is **not a rate limit** — there is no quota you can
wait out. It is a verdict on your fingerprint, which is why this tool backs off
for hours rather than retrying.

### The causes, in order of likelihood

#### 1. You are on a datacenter or VPN IP

**By far the most common.** Cloud providers, VPS hosts, and commercial VPN
ranges are blocked as a category.

Test whether this is you:

```bash
curl -s https://ipinfo.io/org
```

If that prints a hosting company — Hetzner, DigitalOcean, Amazon, OVH, a VPN
provider — this is your problem.

**Fix:** move the poller to a residential connection. A Raspberry Pi at home is
the ideal answer. There is no header, cookie, or configuration that fixes a
blocked IP range.

See [Deployment](deployment.md#where-to-run-it).

#### 2. Your User-Agent is stale

Too Good To Go's Android app version moves, and the client string carries it.
DataDome fingerprints on that string, and a stale one is both suspicious and
shared with every other user of the underlying library.

**Check what the server is using:**

```bash
tgtg-alert login     # prints the resolved UA and where it came from
```

If it says `fallback (could not reach Play Store)`, it guessed.

**Fix:** find the current version on the Play Store listing for Too Good To Go,
then:

```bash
TGTG_USER_AGENT='TGTG/<version> Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Pro Build/AP2A.240905.003)' \
  tgtg-alert login
```

The format must match exactly. A malformed string is worse than the default.

#### 3. You are polling too often

Raise the interval:

```bash
TGTG_POLL_INTERVAL=1800    # 30 minutes
```

Then wait a day and step it back down gradually. Do not return straight to a
fast poll — reputation recovers slowly.

#### 4. Locale

A handful of reports describe persistent 403s that cleared when
`accept-language` changed:

```bash
TGTG_LANGUAGE=en-US
```

The mechanism is not understood and it is a workaround, not an explanation. Try
it only after the above.

### What not to do

- **Don't restart the service repeatedly.** It resets nothing; the block is on
  the network, and each restart attempts a fresh poll that deepens it.
- **Don't lower the poll interval** hoping to catch up. That makes it worse.
- **Don't retry in a loop.** The client library already retries a 403 once
  internally; a second retry layer is how a temporary block becomes permanent.

### How it resolves

On its own. The backoff escalates 1h → 2h → 4h → capped at 6h, and alerts resume
automatically once requests start succeeding again. There is nothing to fix if
the cause was transient.

If the cause was a datacenter IP, it will not resolve — the block is permanent
until you move.

### If you think this is unfair

It is worth being honest: if Too Good To Go serves you challenges, that may
simply be the protection working as intended. This tool is built to be a polite
client, but it is still an automated client against an API whose terms forbid
automated clients. See
[The Too Good To Go problem](the-tgtg-problem.md).

This project will not help with CAPTCHA solving, fingerprint forgery, or proxy
rotation to evade a block. Those cross from *automating access* into
*circumventing protection*, which is a different thing.

---

## Not logged in

```
ERROR tgtg_alert.poller: no TGTG credentials stored -- run `tgtg-alert login` first
```

Or in the app: *"Server is not logged in to Too Good To Go."*

**Fix:**

```bash
tgtg-alert login
```

**If it worked before and stopped**, the session was rejected — usually the same
DataDome cause as above. Fix that first, then log in again.

**If you are running with Docker**, note that `login` must be run explicitly
since it is interactive:

```bash
docker compose run --rm tgtg-alert login
```

**Check the database is being found.** If `TGTG_DATA_DIR` is relative and the
service starts from a different working directory, it finds an empty database.
Set an absolute path:

```bash
TGTG_DATA_DIR=/var/lib/tgtg-alert
```

---

## Login problems

### The PIN never arrives

- Check spam.
- Confirm the email matches a Too Good To Go account. If not, the API returns
  `state: TERMS` and the tool reports that the email is not linked to an account.
- Try requesting again after a few minutes.

### "Opening the email on my phone doesn't work"

Correct, and it is a quirk of the API rather than a bug here. If the TGTG app is
installed on the phone you read the email on, it intercepts the login link and
the flow never completes.

**Open the email on a computer.**

### The PIN is rejected

- Six digits, no spaces.
- It expires. Request a fresh one.
- Repeated failures make DataDome's opinion of you worse — wait before retrying
  in a loop.

### Login fails with 403

See [Blocked](#blocked-403--datadome). Login is subject to the same protection as
polling.

---

## Nothing matches

The server is polling fine, but `TRACKED` stays at 0.

### Is the pattern right?

`--store` and `--bag` are **case-insensitive substring** matches. No wildcards,
no regex, no fuzzy matching.

```bash
# These match "Blank Street Coffee":
--store "Blank Street"
--store "blank street"
--store "Blank"

# This does not:
--store "Blank St. Coffee"    # punctuation must match
```

**The reliable way to find the exact name:** the app's **Discover** tab. It
searches live, shows the real store and bag names, and creates a watch from a
result with the pattern prefilled.

### Is the radius big enough?

The centre point must be near the store. Coordinates that are slightly off are
usually fine at 5–10 km, but a watch centred on the wrong city will match
nothing.

```bash
tgtg-alert watch list      # check the RADIUS column
```

### Is the price ceiling too low?

`--max-price 3` excludes a 3.99 bag. Note that an item whose price *cannot be
read* passes the ceiling rather than failing it, so this is rarely the cause of
zero matches.

### Is the watch enabled?

```bash
tgtg-alert watch list      # check the ON column
tgtg-alert watch update 1 --enable
```

### Turn up the detail

```bash
TGTG_LOG_LEVEL=DEBUG tgtg-alert poll --dry-run
```

`DEBUG` logs each candidate item and why it was or was not matched. That will
tell you immediately whether the store is appearing at all.

**If the store never appears in the logs**, Too Good To Go is not returning it
for your coordinates — usually because it has no bags listed right now, which is
normal outside meal times.

---

## No alerts, but everything looks fine

The server polls, items match, but you are not being notified.

### Work through it

1. **Is there an alert in the Activity tab?**
   - **Yes, but no notification** → delivery problem. Go to
     [Notifications not arriving](#notifications-not-arriving).
   - **No** → the decision logic is not firing. Go to step 2.

2. **Has the watch baselined?**
   ```bash
   tgtg-alert watch list
   ```
   `(awaiting first poll)` means it has not. Wait one interval.

3. **Is it the baseline problem?** The first poll of a watch is silent *by
   design*. If you added the watch while bags were already available, you were
   not told about them — only about changes from that point on.

   If the server was off for a long time and everything looks "new", re-baseline:
   ```bash
   tgtg-alert watch update 1 --rebaseline
   ```

4. **Is the stock actually changing?** This is the one people miss.

   The rule is **0 → >0**: a bag that was sold out and came back, or a bag that
   is genuinely new. A bag that has been steadily available for three days will
   never alert, because nothing changed.

   To confirm the mechanism works, watch for a `restock` or `new` in the logs:
   ```bash
   tgtg-alert poll --dry-run
   ```
   On a busy store you should eventually see `[dry-run] would alert:` lines.

5. **Want more alerts?** Per watch, opt into count increases:
   ```bash
   tgtg-alert watch update 1
   # or recreate with --notify-on-increase
   ```
   Or from the app's watch form. Noisy — it fires every time more bags are added.

---

## Notifications not arriving

`test-notify` reports success but nothing appears on the phone.

### Android

1. **Check the channel importance.** Android Settings → Apps → TGTG Alert →
   Notifications → **Bag alerts**. If the user (or a battery optimiser) lowered
   it, the app cannot detect or fix that. Delete and reinstall to recreate the
   channel at maximum importance, or raise it manually.
2. **Check Do Not Disturb.** The channel bypasses DND only if the user allowed
   it.
3. **Check battery optimisation.** Aggressive OEM battery managers (Xiaomi,
   Huawei, Samsung) can suppress push entirely. Set the app to unrestricted.
4. **Android 15+ Notification Cooldown** progressively quiets apps that alert
   repeatedly in a short window. This tool sends one alert per transition
   precisely to avoid triggering it — but a misconfigured watch with
   `--notify-on-increase` could.

### iOS

1. **Are you on a real device?** The iOS Simulator *cannot* receive push
   notifications. Ever.
2. **Are you running in Expo Go?** Push has not worked in Expo Go since SDK 53.
   You need a development or production build.
3. **Check Focus modes.** Alerts use the `time-sensitive` interruption level,
   which breaks through Focus — but only if the user has allowed time-sensitive
   notifications for the app.
4. **Check Settings → Notifications → TGTG Alert** and confirm alerts are not
   delivered quietly.

### Both

- **Re-register the device.** Settings → *Register this device*, or reinstall.
  Tokens rotate.
- **Check the server log** for delivery errors.
- **Set `TGTG_WEBHOOK_URL`** as a diagnostic. If webhooks arrive but push does
  not, the problem is isolated to push delivery — and you have a working fallback
  in the meantime.

---

## Push token died

```
DeviceNotRegistered
```

The app was uninstalled, or the token rotated. The server prunes these
automatically, so this is informational.

**Fix:** open the app and it re-registers on launch. Or Settings → *Register this
device*.

---

## No devices paired

```
no devices paired and no webhook configured; alert dropped
```

No phone is paired, so alerts have nowhere to go. They are still written to the
alert log (visible in the Activity tab once you pair), but nothing is delivered.

**Fix:**

```bash
tgtg-alert pair      # then scan in the app
tgtg-alert devices   # confirm it registered
```

---

## Timeouts and connection failures

```
fetch failed for bucket 51.51:-0.13: HTTPSConnectionPool(...): Read timed out
```

**Transient network trouble.** The pass skips that bucket and retries next cycle.
Occasional occurrences are harmless.

**If it is constant:**

```bash
# Confirm the machine has outbound connectivity at all
curl -sI https://apptoogoodtogo.com/api/

# Give it more time
TGTG_HTTP_TIMEOUT=45
```

**If DNS is the problem**, check `/etc/resolv.conf`. A Pi with a flaky router is
a common source.

**If it started after a network change**, confirm the machine is not now routing
through a VPN — see [Blocked](#blocked-403--datadome).

---

## The API moved

```
TGTGLoginError: 404
AttributeError: 'NoneType' object has no attribute ...
```

Too Good To Go changed an endpoint. The item endpoint has moved `v7 → v8 → v9`
over the years, and each move breaks clients until the library catches up.

**Check whether the library has been updated:**

```bash
cd server
.venv/bin/pip install --force-reinstall --no-deps \
  "git+https://github.com/ahivert/tgtg-python.git"
.venv/bin/python -c "import tgtg; print(tgtg.API_ITEM_ENDPOINT)"
```

If that prints a newer version number than before, the fix has landed — restart
and retry.

**If it has not been updated yet**, the honest answer is to wait, or to open an
issue on the library. This project installs from git master rather than PyPI
precisely because the released version lags behind; see
[Development](development.md#why-tgtg-comes-from-git).

**If the error mentions a field**, the response shape changed. The normalizer
logs what it could not parse:

```
WARNING item with no id, skipping: keys=['displayName', 'quantity', ...]
```

That output is genuinely useful — it is the new field names. Open an issue with
it.

---

## The API or app will not connect

### From the phone

**The phone cannot reach the server URL.** Check, in order:

1. **Is the server running?**
   ```bash
   curl http://localhost:8787/health
   ```
2. **Are they on the same network?** A phone on mobile data cannot reach a LAN
   address. Use Tailscale or a reverse proxy — see
   [Deployment](deployment.md#reaching-it-from-outside-your-network).
3. **Is a firewall blocking it?**
   ```bash
   sudo ufw allow 8787/tcp     # if you use ufw and want it public
   ```
4. **Is the URL right?** `192.168.x.x`, not `localhost` — `localhost` on the
   phone means the phone.
5. **Did you change the port?** Re-run `tgtg-alert pair`.

### Getting 401

The API token does not match. Re-pair:

```bash
tgtg-alert pair
```

If you regenerated `TGTG_API_TOKEN` (or ran `init --force`), every paired device
holds the old value.

---

## Diagnosing anything else

### Get the full picture

```bash
# What does the server think is going on?
curl -s -H "Authorization: Bearer $TGTG_API_TOKEN" \
  http://localhost:8787/api/status | jq

# What have the recent polls done?
curl -s -H "Authorization: Bearer $TGTG_API_TOKEN" \
  http://localhost:8787/api/runs?limit=20 | jq

# What have we alerted, and did it deliver?
curl -s -H "Authorization: Bearer $TGTG_API_TOKEN" \
  http://localhost:8787/api/alerts?limit=20 | jq
```

### Turn up logging

```bash
TGTG_LOG_LEVEL=DEBUG tgtg-alert poll --dry-run
```

### Watch it live

```bash
sudo journalctl -u tgtg-alert -f        # systemd
docker compose logs -f tgtg-alert       # Docker
```

### Before opening an issue

Include:

- The output of `tgtg-alert poll --dry-run` at `DEBUG` level.
- Whether `test-notify` works.
- **Where the server runs** — residential or datacenter. This is the answer more
  often than anything else, and it is the first thing anyone will ask.
- The `last_run` block from `/api/status`.

**Redact your tokens.** `access_token`, `refresh_token`, `cookie`, and
`TGTG_API_TOKEN` should never appear in a bug report. The database is a live
session.
