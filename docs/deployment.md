# Deployment

Making it run reliably, and keeping it running.

---

## Where to run it

**This matters more than how you run it.**

Too Good To Go's API sits behind [DataDome](https://datadome.co/), which blocks
datacenter and VPN IP ranges as a matter of course. The practical consequence:

> A cloud VPS is the single most likely way to end up with a watcher that runs
> cleanly, logs no errors, and never alerts.

This is counterintuitive enough to be worth restating. The failure is silent.
Everything looks healthy — the process is up, the API responds, the app connects
— while every poll to Too Good To Go is being refused at the edge.

**Good:**

| Option | Why |
|---|---|
| **Raspberry Pi** | Ideal. Always on, a few watts, residential IP. |
| **An old laptop or desktop** | Fine, if you already leave it running. |
| **A NAS** | Fine, if it can run Docker or Python. |
| **Your daily machine** | Works, but alerts stop when it sleeps. |

**Bad:**

| Option | Why |
|---|---|
| Any cloud VPS (Hetzner, DigitalOcean, Lightsail…) | Datacenter IP. Blocked. |
| Fly.io, Railway, Render | Datacenter IP. Blocked. |
| Behind a commercial VPN | VPN ranges are blocked too. |
| A server at your office | Usually a business connection with its own reputation. |

There is no configuration that fixes a blocked IP. Header tuning does not help;
the block is on the network, not the request. The fix is to move the poller, not
to tune it.

### If you only have a VPS

You can split the two halves. The API can live anywhere; **only the poller needs
a residential IP**.

```bash
# On the VPS — API only, reachable from the internet
tgtg-alert serve --only api

# At home — poller only, talking to the same database
tgtg-alert serve --only poller
```

This needs the two to share `data/tgtg_alert.db`, which in practice means either
running both on the home machine, or syncing the database (awkward, and unsafe
to do while both are writing). Honestly: **just run the whole thing at home** and
expose it with Tailscale if you need remote access.

---

## Docker

The simplest path, and the one that survives reboots with no extra work.

```bash
git clone https://github.com/WalkTheEarth/tgtg-alert.git
cd tgtg-alert
cp .env.example .env      # or run `init` locally and copy the file
docker compose up -d
```

The bundled `docker-compose.yml`:

- builds from `server/`,
- mounts `./data` for the database,
- reads `.env`,
- restarts unless stopped,
- runs as an unprivileged user (uid 10001),
- has a healthcheck hitting `/health`.

`/health` is deliberately unauthenticated so the healthcheck works without the
token. It returns only `{"ok": true, "version": "..."}` — nothing sensitive.

### Logging in with Docker

`login` is interactive, so run it as a one-off:

```bash
docker compose run --rm tgtg-alert login
```

The credentials land in the mounted database and the running container picks them
up.

### Other commands

```bash
docker compose exec tgtg-alert tgtg-alert watch list
docker compose exec tgtg-alert tgtg-alert poll --dry-run
docker compose exec tgtg-alert tgtg-alert pair
docker compose exec tgtg-alert tgtg-alert test-notify
```

`pair` prints a QR to the terminal; it works fine through `docker compose exec`.

### Building without compose

```bash
cd server
docker build -t tgtg-alert .
docker run -d --name tgtg-alert \
  --restart unless-stopped \
  -p 8787:8787 \
  -v "$PWD/../data:/data" \
  --env-file ../.env \
  -e TGTG_DATA_DIR=/data \
  tgtg-alert
```

---

## systemd

Without Docker. Assumes the checkout is at `/opt/tgtg-alert` and you created a
dedicated user.

```bash
sudo useradd --system --home /opt/tgtg-alert --shell /usr/sbin/nologin tgtg
sudo chown -R tgtg:tgtg /opt/tgtg-alert
```

`/etc/systemd/system/tgtg-alert.service`:

```ini
[Unit]
Description=TGTG Alert
Documentation=https://github.com/WalkTheEarth/tgtg-alert
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tgtg
Group=tgtg
WorkingDirectory=/opt/tgtg-alert/server
EnvironmentFile=/opt/tgtg-alert/server/.env
ExecStart=/opt/tgtg-alert/server/.venv/bin/tgtg-alert serve
Restart=always
RestartSec=30

# Give up if it crash-loops; a config error should be visible, not silent.
StartLimitIntervalSec=300
StartLimitBurst=5

# Hardening. The service needs to write its data directory and nothing else.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/tgtg-alert/server/data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tgtg-alert
sudo systemctl status tgtg-alert
sudo journalctl -u tgtg-alert -f          # follow the logs
```

**Set `TGTG_DATA_DIR` to an absolute path** in `.env` when running as a service.
A relative path resolves against the working directory, and a service that starts
somewhere unexpected finds an empty database and reports you are logged out.

---

## Reaching it from outside your network

Only needed for alerts while away from home. If your phone is always on the same
wifi, skip this — the API is not exposed and that is the safest configuration.

### Tailscale (recommended)

No ports opened, no certificates to manage, and the service stays invisible to
the internet.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Then pair using the Tailscale hostname:

```bash
tgtg-alert pair --url http://your-host.tailnet-name.ts.net:8787
```

Install Tailscale on the phone, and it works anywhere.

### Reverse proxy with TLS

If you want a normal public URL. **Never expose this over plain HTTP** — the API
token travels in a header on every request.

Caddy is the least work:

```caddy
tgtg.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

Caddy obtains and renews the certificate automatically. Then:

```bash
# Bind to loopback only, so the proxy is the only way in
TGTG_HOST=127.0.0.1

tgtg-alert pair --url https://tgtg.example.com
```

**Add authentication at the proxy** if it is public. The API token is strong,
but a publicly reachable endpoint is a larger target than it needs to be. Caddy:

```caddy
tgtg.example.com {
    basicauth {
        you $2a$14$...   # caddy hash-password
    }
    reverse_proxy 127.0.0.1:8787
}
```

> If you put basic auth in front, the phone app cannot pair through it — it sends
> only the bearer token. Pair on the LAN, then use the public URL, or skip basic
> auth and rely on the token plus a firewall.

---

## Backups

Back up `data/tgtg_alert.db`. It holds your session, watches, and alert history.

SQLite in WAL mode has a `-wal` sidecar, so **copy it properly** rather than
`cp`-ing the file out from under a running process:

```bash
sqlite3 data/tgtg_alert.db ".backup '/backup/tgtg-$(date +%F).db'"
```

Or stop the service first and copy the directory.

**Backups contain a live Too Good To Go session.** Encrypt them, and do not put
them anywhere shared.

Truthfully, losing the database is not catastrophic: re-run `login`, re-add your
watches, and you are back in a few minutes. The alert history is the only
irreplaceable part, and it is not important.

---

## Upgrades

```bash
cd tgtg-alert
git pull

# Bare metal
cd server && .venv/bin/pip install -e .

# Docker
docker compose up -d --build
```

The schema is created with `CREATE TABLE IF NOT EXISTS` and the app calls
`init_db` on every start, so new tables appear automatically. **There is no
migration system** — a column change would need manual `ALTER TABLE`. For a
project this size that is a reasonable trade, but be aware of it if you are
running something you modified.

**Re-run `login` after upgrading** if the release notes mention the API version.
Endpoints move, and a stale session sometimes needs refreshing alongside.

---

## Watching it work

`serve` logs a summary every pass:

```
17:02:44 INFO  tgtg_alert.poller: poller started; interval 600s
17:02:44 INFO  tgtg_alert.poller: bucket 51.51:-0.13: 62 items across 2 watch(es)
17:02:44 INFO  tgtg_alert.poller: pass complete: 2 watch(es), 62 item(s), 5 match(es), 1 alert(s)
```

What to look for:

| Line | Meaning |
|---|---|
| `pass complete: ...` | Healthy. |
| `no enabled watches` | Nothing to do — add one, or check they are enabled. |
| `TGTG refused the request (HTTP 403` | Blocked. Read the guidance it prints. |
| `pass aborted: TGTG is blocking this host` | Blocked mid-pass, backing off. |
| `no devices paired and no webhook configured` | Alerts are being dropped. |

At `WARNING` level most of this disappears. **If you raise the log level, watch
the app's status screen instead** — a blocked poller is otherwise completely
silent.

Since every pass is recorded in `poll_runs`, you can also check without logs:

```bash
curl -s -H "Authorization: Bearer $TGTG_API_TOKEN" \
  http://localhost:8787/api/runs?limit=10 | jq
```

`blocked: 1` on recent runs means Too Good To Go is refusing you.

---

## Resource use

Tiny. A pass every ten minutes, a handful of HTTP requests, and a few megabytes
of SQLite. It runs comfortably on a Raspberry Pi Zero. There is no reason to
give it more than 256 MB of RAM.

The one thing it does need is a **stable network** — a flaky connection produces
timeouts, which look like missing data rather than errors.
