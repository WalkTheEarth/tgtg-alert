# Security

What secrets exist, where they live, what an attacker could do with them, and
what to do when one leaks.

This is a small self-hosted tool, not a bank. But it holds a **live session for a
real account**, and that deserves knowing about.

---

## The two secrets

They are different, they live in different places, and confusing them is easy.

### 1. The TGTG session — `data/tgtg_alert.db`

Your Too Good To Go `access_token`, `refresh_token`, and DataDome `cookie`, in a
SQLite database.

**What it grants:** whoever holds this *is* you on Too Good To Go, until the
session is revoked. They could read your order history, create orders, and cancel
them. They cannot change your password or payment details through this API, but
they can act as you within the app's surface.

**Why it is in a database rather than a config file:** the refresh token rotates
roughly every four hours and the poller writes the new one every time. A config
file is static input; a credential that changes constantly belongs in storage
that is meant to be written.

**Protection:** filesystem permissions. `0600` on the file, and the directory it
lives in should not be world-readable. It is gitignored.

### 2. The API token — `.env`

The shared secret your phone uses to authenticate to your server.

**What it grants:** whoever holds it can read your watch rules, create and delete
watches, and **send push notifications to your phone**. They cannot reach Too
Good To Go with it — it is not your TGTG credential.

**Protection:** `chmod 600`, and gitignored.

### Comparison

| | TGTG session | API token |
|---|---|---|
| Lives in | `data/tgtg_alert.db` | `.env` |
| Grants access to | Your Too Good To Go account | Your server |
| Rotates | Automatically, every ~4h | Only when you change it |
| Blast radius | Orders, history, account | Watches, push spam to your phone |
| Severity if leaked | **High** | Moderate |

**The database is the more sensitive of the two.** Both should be treated as
secrets, but if you can only protect one, protect the database.

---

## What is not stored

Worth stating, because it is reassuring and it bounds the damage:

- **Your Too Good To Go password.** There is no password — the login flow is an
  emailed PIN, and the PIN is never stored.
- **Payment details.** The API client cannot pay, and this tool never calls the
  order endpoints.
- **Your email address in the clear** beyond the account identifier in the
  database, which is needed to display "logged in as".
- **Any location history.** Watch coordinates are stored; nothing tracks where
  the *phone* has been.
- **Any telemetry.** Nothing is sent anywhere except Too Good To Go and your
  chosen push/webhook endpoints.

---

## The network surface

The API listens on `0.0.0.0:8787` by default, with bearer-token auth.

Everything it serves is behind the token **except `/health`**, which returns
`{"ok": true, "version": "..."}`. That is unauthenticated on purpose, so
container healthchecks work without embedding the token. It leaks the version
number and nothing else.

**Best practice, in order:**

1. **Don't expose it at all.** If your phone is on the same wifi, you are done.
   This is the right answer for most people.
2. **Tailscale or similar.** No open ports, no certificates, invisible to the
   internet.
3. **Reverse proxy with TLS, bound to loopback.** Set `TGTG_HOST=127.0.0.1` so
   the only way in is through the proxy.
4. **Never plain HTTP over the open internet.** The token travels in a header on
   every request.

Details in [Deployment](deployment.md#reaching-it-from-outside-your-network).

---

## If a secret leaks

### The API token

Straightforward:

```bash
# 1. Generate a new one
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Put it in .env as TGTG_API_TOKEN

# 3. Restart
sudo systemctl restart tgtg-alert     # or: docker compose restart

# 4. Re-pair every phone — the old token no longer works
tgtg-alert pair
```

The old token is dead the moment the server restarts. Nothing else needs doing —
no session to revoke, no external service to notify.

### The TGTG session

Less clean, because the session belongs to Too Good To Go, not to you.

```bash
# 1. Log in again — this replaces the stored session
tgtg-alert login
```

That overwrites `access_token`, `refresh_token`, and `cookie`. The old tokens
become useless **once they expire**, which is within about four hours for the
access token; the refresh token you replaced is the one that mattered, and
replacing it in the database invalidates your copy.

To revoke server-side as well, **change your Too Good To Go account** — the app
has a logout-everywhere behaviour by logging out of the mobile app, which
invalidates sessions. If you are worried enough to be doing this, also change
your email account password, since the login flow runs through it.

Then check the app for orders you did not place.

### If the database itself was exposed

Assume the session is compromised. Re-run `login`, and consider whether the
machine's other secrets were reachable too — a database leak usually means a
broader compromise.

---

## Hardening checklist

For a box you care about:

- [ ] `.env` is `chmod 600` (`init` does this)
- [ ] `data/` is not world-readable
- [ ] The service runs as a non-root user (`--user 10001` in Docker, `User=` in
      systemd)
- [ ] `TGTG_HOST=127.0.0.1` if you use a reverse proxy
- [ ] TLS if it is reachable from the internet
- [ ] `EXPO_ACCESS_TOKEN` set, if you use Expo push
- [ ] Backups are encrypted, or you accept losing a re-creatable session
- [ ] `git status` in your checkout shows no `.env` or `data/`

The bundled systemd unit and Dockerfile already apply most of these.

---

## A note on the honesty of this page

Everything above is about protecting *you*. There is a separate question about
your risk *from* Too Good To Go, which is a Terms of Service matter rather than a
security one — and it is covered properly in
[The Too Good To Go problem](the-tgtg-problem.md).

The short version: running this is a breach of their terms, the realistic
consequence is a blocked IP or a closed account, and you should use an account
you can afford to lose. That is not a security vulnerability in this software.
It is the nature of what the software does, and no amount of hardening changes
it.
