# TGTG Alert

Watch Too Good To Go for the bags *you* care about, and get a push
notification the moment one shows up.

Self-hosted, open source, and deliberately without a central server: **you run
the watcher, you own the data, nobody else holds your Too Good To Go session**.
The phone app is a thin client that pairs with your own instance.

---

## ⚠️ Read this first

**This uses an unofficial, undocumented API, and doing so is against Too Good
To Go's Terms of Service.** You should decide whether that is acceptable to you
before you invest time here.

The relevant clause (§7.5, "TGTG Rules of Conduct") is unqualified:

> "You will not use any automated systems, robots or software to extract data
> from the Too Good To Go Marketplace."

There is no personal-use exception, no public API, and no partner programme you
can sign up for. TGTG also reserves the right to suspend accounts "at any time
with or without notice" (§11.1).

What that means in practice:

- **The realistic risk is your account and/or IP being blocked, not legal
  action.** People running similar tools have reported being blocked by
  DataDome, TGTG's bot protection. A blocked account means losing your order
  history and any active orders.
- **Use an account you can afford to lose.** Not the one with unspent credit.
- **This tool is built to be as polite as possible** — conservative polling,
  escalating backoff, no retry storms — but politeness reduces the risk, it
  does not eliminate it.
- **Expect breakage.** The API is private and changes without notice. The
  upstream client library is community-maintained and occasionally needs
  updating when TGTG shifts an endpoint.

If any of that is a problem, the honest answer is that there is no compliant
way to build this today.

---

## Why this needs a server

The obvious design — an app that polls in the background and buzzes you — does
not work. This is not a limitation of any particular framework; both mobile OSes
forbid it:

- **iOS** has no guaranteed background refresh interval at all. Apple's own
  developer support is blunt about sub-30-second refresh: *"There is no way to
  get resumed (or relaunched) in the background at that rate."* In practice you
  get a few unpredictable wake-ups a day at times the system chooses.
- **Android** enforces a hard 15-minute floor on periodic work, and worse, its
  Doze and App Standby modes **disable background networking entirely** for apps
  you rarely open — which a stock-alert app inevitably becomes.

Since bags appear at unpredictable times and often sell out within minutes, an
on-device poller would miss most of them. So something has to poll on a real
schedule. That something is a small service you run yourself.

## Architecture

```
                    ┌──────────────────────────────┐
                    │  your machine / Pi / NAS     │
                    │                              │
   TGTG API ◄───────┤  poller ──► matcher ──► push │
  (unofficial)      │     │                    │   │
                    │     └──► SQLite          │   │
                    │                          │   │
                    │  HTTP API ◄──────────┐   │   │
                    └──────────────────────┼───┼───┘
                                           │   │
                              pairing QR   │   │  push
                                           │   ▼
                                    ┌──────┴────────┐
                                    │  phone app    │
                                    │ (iOS/Android) │
                                    └───────────────┘
```

The poller asks TGTG what is available near your saved locations, compares the
answer against what it saw last time, and pushes a notification when something
changes for the better.

## How it decides to alert

Getting this right is most of the work, because the naive version either spams
you or stays silent:

| Situation | Behaviour |
|---|---|
| **First ever poll** | Silent. Records what is already there. Otherwise setup fires a notification for every bag in stock. |
| **Sold out → available** (`0 → >0`) | **Alerts.** The main event. |
| **A bag you have never seen appears** | **Alerts.** A genuinely new listing. |
| **Still available** (`4 → 4`) | Quiet. A bag sitting there all afternoon is not news. |
| **More available** (`2 → 6`) | Quiet by default; opt in per watch with `--notify-on-increase`. |
| **Available → sold out** | Quiet, but remembered — this is what makes the next `0 → >0` detectable. |

An item that vanishes from TGTG's response is treated as sold out, so detection
works even if the API omits out-of-stock items.

---

## Quick start

### 1. Run the server

```bash
git clone https://github.com/WalkTheEarth/tgtg-alert.git
cd tgtg-alert/server

python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/tgtg-alert init           # writes .env and the database
.venv/bin/tgtg-alert login          # emails you a PIN; interactive, one time
```

`login` is the only interactive step. It stores a session token in the local
database — that database is now a secret, so keep it off git (the bundled
`.gitignore` already does).

### 2. Add a watch

```bash
# Anything at a particular chain, within 5km
.venv/bin/tgtg-alert watch add --lat 51.5072 --lon -0.1276 --radius 5 \
    --store "Blank Street" --max-price 5

# Only a specific bag type
.venv/bin/tgtg-alert watch add --lat 51.5072 --lon -0.1276 \
    --store "Pret" --bag "Magic Bag"

# Everything nearby, cheap
.venv/bin/tgtg-alert watch add --lat 51.5072 --lon -0.1276 --radius 2 --max-price 4
```

Check it works before trusting it:

```bash
.venv/bin/tgtg-alert poll --dry-run   # one pass; logs what it would alert on
.venv/bin/tgtg-alert watch list
```

### 3. Serve

```bash
.venv/bin/tgtg-alert serve      # API + poller in one process
```

Or with Docker:

```bash
docker compose up -d
```

### 4. Pair your phone

```bash
.venv/bin/tgtg-alert pair       # prints a QR code
```

Scan it in the app. That is the whole setup — the QR carries the server URL and
its access token.

---

## The phone app

```bash
cd mobile
npm install
npx expo start                  # scan with Expo Go to try it immediately
```

### Building

**Android** builds on any OS, including Linux:

```bash
npx eas build --platform android --profile preview   # APK for sideloading
```

**iOS requires macOS or a cloud build.** There is no way around this — Apple's
toolchain only runs on macOS. [EAS Build](https://expo.dev/eas) compiles and
signs it in the cloud from any OS, and the free tier (15 builds/month) is more
than enough. You will need an Apple Developer Program membership ($99/year) for
a build you can actually install; EAS handles the certificates and provisioning
profiles for you.

```bash
npx eas build --platform ios --profile preview
```

### What the app does

- **Watches** — create, edit, pause and delete the rules the server enforces.
- **Discover** — searches TGTG live near you and lets you tap a result to build
  a watch from it, which beats guessing at exact store names.
- **Activity** — what has actually been alerted, and whether it was delivered.
- **Status** — surfaces a blocked or failing poller instead of letting it fail
  silently, which is the failure mode that matters most here.

---

## Where to run it

**Run it at home.** This genuinely matters and it is counterintuitive.

TGTG sits behind [DataDome](https://datadome.co/), which blocks datacenter and
VPN IP ranges as a matter of course. A cheap cloud VPS is therefore the single
most likely way to end up with a watcher that looks healthy, logs no errors, and
never alerts. Residential connections are far more reliable.

Good options: a Raspberry Pi, an old laptop, a NAS, or the machine you already
leave on. If you must use a VPS, expect to solve the 403 problem yourself.

The app does not need to be reachable from the internet if your phone is on the
same network. If you want alerts while out, put it behind a reverse proxy with
TLS (Caddy and Tailscale are both easy) and pass `--url` to `pair`.

---

## Configuration

Set via environment or `.env`:

| Variable | Default | Notes |
|---|---|---|
| `TGTG_DATA_DIR` | `./data` | Where the database lives. |
| `TGTG_API_TOKEN` | generated | Shared secret the phone uses. |
| `TGTG_POLL_INTERVAL` | `600` | Seconds between polls. **Slower is safer.** Floor of 300. |
| `TGTG_PORT` | `8787` | API port. |
| `TGTG_LANGUAGE` | `en-GB` | `accept-language`; can affect what TGTG returns. |
| `TGTG_USER_AGENT` | current TGTG version | See troubleshooting. |
| `EXPO_ACCESS_TOKEN` | unset | Optional; enables Expo push security. |
| `TGTG_WEBHOOK_URL` | unset | POST alerts here too (ntfy, Discord, Home Assistant…). |

`TGTG_WEBHOOK_URL` is worth knowing about: it lets you get alerts without the
phone app at all, and it is the easiest way to verify the pipeline end to end:

```bash
TGTG_WEBHOOK_URL=https://ntfy.sh/your-topic .venv/bin/tgtg-alert test-notify
```

---

## Troubleshooting

### Alerts stopped, logs show HTTP 403

This is DataDome, and it is the most common failure. It is a verdict on your
*client fingerprint*, not a quota — so retrying makes it worse, and this tool
deliberately backs off for an hour instead. In order of likelihood:

1. **You are running on a datacenter or VPN IP.** Move it to a home connection.
   This is the cause more often than everything else combined.
2. **Your User-Agent is stale.** TGTG's current Android version moves; the
   client library's built-in fallback is roughly a year behind, and *every*
   user of that library shares it, which makes it trivially detectable. Set
   `TGTG_USER_AGENT` to a current version, e.g.
   `TGTG/26.10.0 Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Pro Build/AP2A.240905.003)`.
3. **You are polling too often.** Raise `TGTG_POLL_INTERVAL`.

Blocks clear on their own; alerts resume automatically. Check
`GET /api/status` (`blocked_in_last_24h`) or the app's status screen.

### "not logged in" after it worked for a while

The session refresh was rejected — usually the same 403 cause. Re-run
`tgtg-alert login`.

### No alerts, but the logs look fine

Check your watches have baselined:

```bash
.venv/bin/tgtg-alert watch list    # a watch awaiting its first poll says so
```

Then confirm delivery independently with `tgtg-alert test-notify`.

### Push works on Android but not iOS

iOS push does not work in Expo Go from SDK 53 onward. You need a development
build (`npx expo run:ios` or an EAS build), and the iOS Simulator can never
receive push notifications — use a real device.

---

## Development

```bash
cd server
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

The interesting logic — when to alert, how responses are normalised, how
backoff escalates — is pure and fully tested without touching the network. See
`tests/test_matcher.py`, `tests/test_normalize.py` and `tests/test_pacer.py`.

## License

GPL-3.0-or-later. This is required in practice as well as chosen: the
underlying [`tgtg-python`](https://github.com/ahivert/tgtg-python) client is
GPL-3.0, so a distributed application linking it must be too.

The mobile app was scaffolded with `create-expo-app` from Expo's
blank-typescript template, which is MIT-licensed; that notice covers the
remaining template boilerplate (`app.json`, `tsconfig.json`, `index.ts`, the
icons) and nothing else. Everything else here is GPL-3.0.

Not affiliated with, endorsed by, or connected to Too Good To Go.
