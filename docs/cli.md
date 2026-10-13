# CLI reference

Every command, flag, and what it actually does.

```
tgtg-alert [--version] [--env-file PATH] <command> [options]

  init          create the env file and database
  login         log in to Too Good To Go (interactive, one time)
  watch         manage watches  (add | list | update | rm)
  devices       list or remove paired phones
  pair          show a QR code to pair the phone app
  poll          run a single poll pass and exit
  test-notify   send a test push to paired devices
  serve         run the API and the poller
  dev           development helpers  (fixture)
```

**Global flags**

| Flag | Meaning |
|---|---|
| `--version` | Print the version and exit. |
| `--env-file PATH` | Read configuration from this file instead of `./.env`. Useful for running several instances from one checkout. |

**Configuration is read at startup** from `.env` in the current directory (or
`--env-file`), then from the real environment. Real environment variables win,
so `TGTG_POLL_INTERVAL=900 tgtg-alert serve` overrides the file. Full list in
[Configuration](configuration.md).

---

## `init`

Creates `.env` and the database.

```bash
tgtg-alert init [--force]
```

| Flag | Meaning |
|---|---|
| `--force` | Overwrite an existing `.env`. **Regenerates the API token**, which unpairs every phone. |

Safe to run repeatedly — it will not clobber an existing `.env` without
`--force`. The database is created if missing and left alone if present.

Writes a token generated with `secrets.token_urlsafe(32)` and sets the file mode
to `0600`.

---

## `login`

Connects your Too Good To Go account. Interactive, and done once.

```bash
tgtg-alert login [--email EMAIL]
```

| Flag | Meaning |
|---|---|
| `--email` | Skip the prompt. |

The flow:

1. Resolves a **User-Agent** — from `TGTG_USER_AGENT` if set, otherwise from the
   current Play Store release. Prints which, and where from.
2. Requests a login code from Too Good To Go.
3. **A 6-digit PIN arrives by email.** Enter it.

```
User-Agent: TGTG/26.10.0 Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Pro Build/AP2A.240905.003)
  (from the current Play Store release)

Requesting a login code from Too Good To Go...
(Check your inbox -- TGTG will email a 6-digit PIN.)
```

**Open the email on a computer.** If the TGTG app is installed on the phone you
read it on, the app intercepts the link and the flow never completes.

On success, credentials are stored in the database — including the resolved
User-Agent, which the poller then reuses. That match matters: DataDome binds its
cookie to the UA that solved the challenge, so presenting a different one later
reads as a replay. See
[Getting started](getting-started.md#why-the-user-agent-matters).

**Re-run this if it says you are logged out.** It overwrites cleanly.

---

## `watch`

### `watch add`

```bash
tgtg-alert watch add --lat LAT --lon LON [options]
```

| Flag | Required | Meaning |
|---|---|---|
| `--lat` | **yes** | Centre latitude. |
| `--lon` | **yes** | Centre longitude. |
| `--radius` | no | Search radius in km. Default `10`. |
| `--store` | no | Case-insensitive substring of the store name. |
| `--bag` | no | Case-insensitive substring of the bag name. |
| `--max-price` | no | Only alert at or below this price, in major units (`5` or `4.50`). |
| `--label` | no | A name for the list view. |
| `--notify-on-increase` | no | Also alert when an already-available bag's count rises. Noisy; off by default. |

All filters combine with **AND**. Omit them all and the watch matches every bag
within the radius.

```bash
# A chain, cheaply, within 5 km
tgtg-alert watch add --lat 51.5072 --lon -0.1276 --radius 5 \
    --store "Blank Street" --max-price 5 --label "Coffee near work"

# One specific bag type
tgtg-alert watch add --lat 51.5072 --lon -0.1276 --store "Pret" --bag "Magic Bag"

# Everything nearby — expect noise
tgtg-alert watch add --lat 51.5072 --lon -0.1276 --radius 2
```

> **Not sure of the exact store name?** Use the app's **Discover** tab. It
> searches live and shows the real names, and tapping a result creates a watch
> with the pattern already filled in.

### `watch list`

```bash
tgtg-alert watch list
```

```
 ID  ON  SEARCH                              RADIUS  TRACKED  IN STOCK
--------------------------------------------------------------------------
  1  on  Coffee store~'Blank Street' <= 5.0     5km       14         2
  2  on  store~'Pret' bag~'Magic Bag'          10km        1         0
  3  off  (any bag)                             2km       37         0
```

| Column | Meaning |
|---|---|
| `ID` | Use with `watch update` and `watch rm`. |
| `ON` | `on`/`off` — whether the poller considers it. |
| `SEARCH` | The rules, in shorthand. `(any bag)` means no filters. |
| `RADIUS` | Search radius. |
| `TRACKED` | Items matching this watch that the server has seen. |
| `IN STOCK` | How many currently have bags available. |

A watch still waiting for its first poll says `(awaiting first poll)`.

**Reading it:** `TRACKED` climbing over a day or two means the rules are matching
real things. `TRACKED: 0` after several polls means the pattern is too narrow or
misspelled — check it against the Discover tab.

### `watch update`

```bash
tgtg-alert watch update WATCH_ID [options]
```

| Flag | Meaning |
|---|---|
| `--enable` / `--disable` | Pause or resume without deleting. State is kept. |
| `--store TEXT` | Change the store pattern. Pass `""` to clear it. |
| `--bag TEXT` | Change the bag pattern. Pass `""` to clear it. |
| `--rebaseline` | Forget the current stock picture and re-survey silently. |

`--rebaseline` also deletes that watch's stored observations.

```bash
tgtg-alert watch update 1 --disable              # pause for a holiday
tgtg-alert watch update 1 --store "New Name"     # the shop rebranded
tgtg-alert watch update 1 --rebaseline           # after the server was off
```

### `watch rm`

```bash
tgtg-alert watch rm WATCH_ID
```

Deletes the watch and its observations. Alerts already sent stay in the log.

---

## `devices`

```bash
tgtg-alert devices [--rm ID]
```

Lists paired phones, with tokens masked — the full token is a capability and is
never printed.

```
#1  ios      Alice's iPhone    ExponentPush...a91f2c
#2  android  Pixel 8           ExponentPush...77b0e4
```

| Flag | Meaning |
|---|---|
| `--rm ID` | Remove that device. It stops receiving alerts immediately. |

Removing a device is the right move when someone stops using the app, or when
push delivery is failing to a phone you no longer have. Dead tokens are also
pruned automatically when Expo reports `DeviceNotRegistered`.

---

## `pair`

```bash
tgtg-alert pair [--url URL]
```

Prints a QR code carrying the server URL and API token, plus the same details as
text for manual entry.

| Flag | Meaning |
|---|---|
| `--url` | The URL the phone should use. Defaults to this host's LAN IP and configured port. |

```bash
# Default: whatever LAN address this machine has
tgtg-alert pair

# Behind a reverse proxy
tgtg-alert pair --url https://tgtg.example.com

# Over Tailscale
tgtg-alert pair --url http://tgtg-pi.tailnet-name.ts.net:8787
```

The token is embedded in the QR, so **treat a screenshot of it as a password**.
Anyone who scans it gets full control of your watches and can push to your phone.

Re-running `pair` issues the same token, so pairing a second phone does not
disturb the first.

---

## `poll`

```bash
tgtg-alert poll [--dry-run]
```

One pass, then exit. What `serve` does on a timer, run once — for testing, or for
driving from an external scheduler like cron.

| Flag | Meaning |
|---|---|
| `--dry-run` | Report what *would* alert. Sends nothing, writes nothing. |

```bash
$ tgtg-alert poll --dry-run
12:04:11 INFO  bucket 51.51:-0.13: 62 items across 2 watch(es)
12:04:11 INFO  [dry-run] would alert: Magic Bag is back at Blank Street | 3 left · 3.99
12:04:11 INFO  pass complete: 2 watch(es), 62 item(s), 5 match(es), 1 alert(s)

2 watch(es), 1 API call group(s), 62 item(s), 5 match(es), 1 alert(s).
```

**This is the best first check after setup.** It exercises credentials, the API,
and the matcher without sending anything.

Exit code is `0` on success, `1` if any bucket errored or credentials are
missing.

Using cron instead of `serve`:

```cron
*/10 * * * * cd /home/you/tgtg-alert/server && .venv/bin/tgtg-alert poll >> /var/log/tgtg.log 2>&1
```

Note that this loses the in-process backoff — each run starts fresh. `serve` is
better if the machine stays on.

---

## `test-notify`

```bash
tgtg-alert test-notify
```

Sends "Test alert" through every configured channel. Exit code `1` if nothing
was delivered.

```
Expo: sent to 1, errors 0
Webhook: ok
```

Use this to separate "the server is not finding bags" from "notifications are not
arriving" — very different problems. If this works and real alerts do not, the
issue is matching or polling. If this fails, the issue is delivery.

---

## `serve`

```bash
tgtg-alert serve [--only {api,poller,both}]
```

Runs the service. Default is both halves in one process — the common self-hosted
case, one container, no supervisor.

| Flag | Meaning |
|---|---|
| `--only api` | HTTP API only. |
| `--only poller` | Poller only. |
| `--only both` | Default. Poller on a daemon thread; Ctrl-C stops both. |

Splitting them is useful when you want the two halves in separate containers, or
when the API sits behind a proxy but the poller must stay on a residential
connection.

```bash
tgtg-alert serve                    # everything
tgtg-alert serve --only poller      # headless box, no API
tgtg-alert serve --only api         # API in a container, poller elsewhere
```

Log output:

```
17:02:44 INFO  tgtg_alert.poller: poller started; interval 600s
17:02:44 INFO  tgtg_alert.poller: bucket 51.51:-0.13: 62 items across 2 watch(es)
17:02:44 INFO  tgtg_alert.poller: alerted (restock): Magic Bag is back at Blank Street
17:02:44 INFO  tgtg_alert.poller: pass complete: 2 watch(es), 62 item(s), 5 match(es), 1 alert(s)
17:02:44 INFO  uvicorn: API listening on http://0.0.0.0:8787
```

---

## `dev`

Development helpers. Nothing here is needed to run the tool normally.

### `dev fixture`

Generates a sample fixture for testing the alert path offline.

```bash
tgtg-alert dev fixture              # print to stdout
tgtg-alert dev fixture --write      # write ./dev-fixture.json
```

| Flag | Meaning |
|---|---|
| `--write` | Write the file instead of printing it. |
| `--path PATH` | Where to write. Default `./dev-fixture.json`. |
| `--force` | Overwrite an existing file. |

Printing to stdout keeps it composable — redirect it wherever you like.

With `--write` it also prints the `.env` lines to add:

```
Add these to .env:

  TGTG_DEV_MODE=1
  TGTG_DEV_FIXTURE=/abs/path/dev-fixture.json
  TGTG_POLL_INTERVAL=20
```

Then edit the fixture between polls to drive a transition. Full walkthrough in
[Development](development.md#dev-mode).

> **Why this exists:** the alert rule is a 0 → >0 stock transition, and you
> cannot make a real shop restock on demand. A fixture is the only practical way
> to test that an alert actually fires — or to exercise the 403 and 429 backoff
> paths without waiting to be blocked for real.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | A failure the command reported — no credentials, a bucket error, delivery failed. |
| `2` | Bad usage: a missing required argument, or an invalid value. |
| `130` | Interrupted with Ctrl-C. |

Useful in scripts: a failed `poll` is detectable, which matters if you drive the
poller from cron and want to alert on failure.

---

## Environment

Every command reads `.env` from the working directory. Run from the same place
every time, or pass `--env-file`:

```bash
tgtg-alert --env-file /etc/tgtg-alert.env serve
```

Full variable list: [Configuration](configuration.md).
