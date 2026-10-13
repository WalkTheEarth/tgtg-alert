# TGTG Alert documentation

Everything about running, configuring and understanding this tool.

**New here?** Start with [Getting started](getting-started.md) — it takes you
from nothing to a working alert. Come back to the rest when you need it.

---

## Read this first

**[The Too Good To Go problem](the-tgtg-problem.md)** — why this uses an
unofficial API, what the Terms of Service actually say, what the realistic risk
is, and when you should walk away. Ten minutes that will save you a weekend.

---

## Guides

| Document | What it covers |
|---|---|
| [Getting started](getting-started.md) | Install, log in, add a watch, pair your phone, get your first alert. |
| [How it works](how-it-works.md) | Why a server is unavoidable, how the poller runs, and exactly when it decides to alert you. |
| [CLI reference](cli.md) | Every command and flag, with examples and real output. |
| [Configuration](configuration.md) | Every environment variable, what it changes, and the trade-off each one makes. |
| [Mobile app](mobile-app.md) | Using the app, push notification setup, and building for Android and iOS. |
| [Deployment](deployment.md) | Where to run it (this matters more than how), Docker, systemd, TLS, backups, upgrades. |
| [Security](security.md) | What secrets exist, where they live, and what to do if one leaks. |
| [Troubleshooting](troubleshooting.md) | Diagnosis playbook. Start here when alerts stop. |
| [HTTP API](api.md) | The REST API the phone app uses — for building your own client. |
| [Development](development.md) | Repo layout, tests, and how to extend it. |

---

## The 60-second version

Too Good To Go bags appear at unpredictable times and sell out in minutes. Both
iOS and Android forbid the kind of background polling an app would need to catch
them, so something has to poll on a real schedule. This is that something: a
small service you run yourself, plus a phone app that pairs with it.

```
TGTG API  ──poll──▶  your server  ──push──▶  your phone
```

Nobody else's server is involved. There is no account to create anywhere, no
telemetry, and no central service holding your Too Good To Go session.

**The one rule that matters:** run it on a home connection, not a VPS. Too Good
To Go blocks datacenter IP addresses, so a cloud box is the most likely way to
end up with a watcher that looks healthy and silently never alerts. See
[Deployment](deployment.md#where-to-run-it).

---

## Quick reference

```bash
tgtg-alert init                    # create .env and the database
tgtg-alert login                   # connect your TGTG account (interactive, once)
tgtg-alert watch add --help        # add a watch
tgtg-alert poll --dry-run          # one pass, send nothing — best first check
tgtg-alert serve                   # run the API and the poller
tgtg-alert pair                    # show the QR code for the phone app
tgtg-alert test-notify             # confirm push delivery end to end
tgtg-alert watch list              # what is being watched, and its state
```

Add `--help` to anything for the full flag list.
