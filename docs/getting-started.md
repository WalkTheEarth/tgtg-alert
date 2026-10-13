# Getting started

From nothing to a working alert. Budget about twenty minutes, most of which is
reading a PIN out of your email.

Before you start, read [The Too Good To Go problem](the-tgtg-problem.md) if you
have not. This tool breaks their Terms of Service, and you should decide that is
acceptable before you spend time on setup.

## What you need

- **A machine that stays on** — a Raspberry Pi, a NAS, an old laptop, or the
  desktop you already leave running. It does *not* need to be reachable from the
  internet to start with.
- **Python 3.9 or newer** on it. (3.11+ recommended; the Docker image ships 3.12.)
- **`git`** — the install pulls one dependency from a git repository. There is a
  reason for that, explained in [Development](development.md#why-tgtg-comes-from-git).
- **A Too Good To Go account**, ideally one you can afford to lose.
- **A phone** for the app. You can run the server without it and use the webhook
  notifier instead — see [Configuration](configuration.md#tgtg_webhook_url).

> **Run it at home.** Not on a VPS, not behind a VPN. DataDome, Too Good To Go's
> bot protection, blocks datacenter IP ranges, and this is the single most common
> reason a setup fails. [Deployment](deployment.md#where-to-run-it) has the detail.

## 1. Install

```bash
git clone https://github.com/WalkTheEarth/tgtg-alert.git
cd tgtg-alert/server

python3 -m venv .venv
.venv/bin/pip install -e .
```

If the install fails complaining about `git`, install git and retry — one
dependency is fetched from GitHub rather than PyPI.

## 2. Initialise

```bash
.venv/bin/tgtg-alert init
```

This creates two things:

- **`.env`** — configuration plus a generated API token, `chmod 600`.
- **`data/tgtg_alert.db`** — a SQLite database, empty for now.

Both are already in `.gitignore`. See [Security](security.md) for what lives
where and why.

## 3. Log in to Too Good To Go

```bash
.venv/bin/tgtg-alert login
```

It asks for your email, then requests a login code from Too Good To Go. **A
6-digit PIN arrives by email** — type it in.

Two things to know:

- **Open the email on a computer, not on the phone with the TGTG app installed.**
  The app intercepts the link and the login flow never completes. This is a
  quirk of how the API works, not something this tool can fix.
- The command prints which **User-Agent** it resolved and where from. That
  matters more than it looks — see [Why the User-Agent matters](#why-the-user-agent-matters).

On success your session is stored in the database. That database is now a
secret: it holds a live Too Good To Go session.

## 4. Add a watch

A watch is "look for these bags, around this point." The centre point is
required; everything else narrows it.

```bash
.venv/bin/tgtg-alert watch add --lat 51.5072 --lon -0.1276 --radius 5 \
    --store "Blank Street" --max-price 5 --label "Coffee near work"
```

You can stack as many as you like. A few shapes worth knowing:

```bash
# Any bag at a chain, within 5 km
tgtg-alert watch add --lat 51.5072 --lon -0.1276 --radius 5 --store "Pret"

# One specific bag type at one store
tgtg-alert watch add --lat 51.5072 --lon -0.1276 --store "Blank Street" --bag "Magic Bag"

# Anything cheap nearby — the firehose
tgtg-alert watch add --lat 51.5072 --lon -0.1276 --radius 2 --max-price 4
```

Wildcards aren't supported; `--store` and `--bag` are case-insensitive
substring matches. Not sure of the exact spelling? Use the app's **Discover**
tab, which searches live and tells you the real names.

## 5. Check it before you trust it

```bash
.venv/bin/tgtg-alert poll --dry-run
```

One pass, sending nothing. It logs what it *would* alert on. If this works,
your credentials and the API integration are good. If it fails, stop here and go
to [Troubleshooting](troubleshooting.md) — there is no point running a service
that cannot poll.

## 6. Run it

```bash
.venv/bin/tgtg-alert serve
```

API and poller in one process. Leave it running under `systemd`, Docker, or
`tmux` — [Deployment](deployment.md) covers making it survive a reboot.

## 7. Pair your phone

In another terminal:

```bash
.venv/bin/tgtg-alert pair
```

A QR code appears carrying the server URL and the API token. Open the app, tap
**Scan QR code**, point it at your terminal.

The phone must be able to reach that URL. On the same wifi, the LAN address it
picks automatically will work. From outside your network you need a reverse proxy
with TLS or a Tailscale-style mesh — see
[Deployment](deployment.md#reaching-it-from-outside-your-network).

## 8. Confirm the whole path

```bash
.venv/bin/tgtg-alert test-notify
```

This sends a real push through the entire chain. Do this before you rely on the
thing — it separates "the server is not finding bags" from "notifications are not
arriving", which are very different problems to debug later.

## What happens next

**Your first poll is silent.** It records what is already available and alerts on
nothing. Otherwise setting up a watch would fire twenty notifications at you for
bags that were already there. From the second poll onward you are told when
something appears.

That means a watch shows as `(awaiting first poll)` until it has run once:

```
 ID  ON  SEARCH                          RADIUS  TRACKED  IN STOCK
  1  on  Coffee store~'Blank Street'       5km        0         0   (awaiting first poll)
```

Give it a poll cycle — ten minutes by default.

Then confirm a watch is actually matching things. `TRACKED` counts the items the
server has seen that match your rules, and `IN STOCK` how many currently have
bags. Both climbing over a day or two means it is working.

Full decision rules: [How it works](how-it-works.md#when-it-alerts-you).

---

## Why the User-Agent matters

Worth understanding, because it explains a whole class of failure.

Too Good To Go's API expects requests to come from their Android app, identified
by a `User-Agent` string carrying the app version. DataDome, the bot protection
in front of it, issues a session cookie **bound to that exact string and to your
IP address**. Present a different one later and it reads as a stolen cookie.

Consequences:

- The tool resolves a **current** app version at login and reuses that exact
  string for every subsequent poll. Both halves must match.
- That string goes stale as Too Good To Go ships updates. A stale one is both
  suspicious on its own and shared with every other user of the client library,
  which makes it trivially fingerprintable.
- `tgtg-alert login` prints what it resolved and where from. If it says
  `fallback (could not reach Play Store)`, it is guessing, and you should set
  `TGTG_USER_AGENT` manually — see
  [Configuration](configuration.md#tgtg_user_agent).

---

## Quick command reference

| I want to… | Command |
|---|---|
| See what is being watched | `tgtg-alert watch list` |
| Pause a watch without deleting it | `tgtg-alert watch update 1 --disable` |
| Change the store pattern | `tgtg-alert watch update 1 --store "New Name"` |
| Re-survey after downtime | `tgtg-alert watch update 1 --rebaseline` |
| Delete a watch | `tgtg-alert watch rm 1` |
| See paired phones | `tgtg-alert devices` |
| Remove a phone | `tgtg-alert devices --rm 1` |
| Test push delivery | `tgtg-alert test-notify` |
| Check what would alert, right now | `tgtg-alert poll --dry-run` |
| Pair another phone | `tgtg-alert pair` |

Every command takes `--help`. Full detail in the [CLI reference](cli.md).

## Next

- [How it works](how-it-works.md) — what the server is actually doing, and when it decides to alert.
- [Configuration](configuration.md) — polling frequency, webhooks, notification tuning.
- [Troubleshooting](troubleshooting.md) — when it stops working.
