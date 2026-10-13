# Development

Repo layout, testing, and extending the thing.

---

## Layout

```
tgtg-alert/
├── server/                      Python: poller + HTTP API
│   ├── src/tgtg_alert/
│   │   ├── config.py            env parsing, defaults, guards
│   │   ├── db.py                schema and connection helpers
│   │   ├── tgtg_source.py       TGTG client wrapper, normaliser, fixtures
│   │   ├── matcher.py           watch matching + the alert decision
│   │   ├── poller.py            the pass: fetch, match, decide, alert
│   │   ├── notify.py            Expo push, webhooks
│   │   ├── api.py               FastAPI app
│   │   └── cli.py               argument parsing and commands
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
└── mobile/                      Expo / React Native app
    ├── App.tsx                  navigation root
    └── src/
        ├── api.ts               server client
        ├── storage.ts           keychain-backed pairing
        ├── notifications.ts     push registration + Android channel
        ├── ConnectionContext.tsx
        ├── components.tsx, theme.ts, types.ts, navigation.ts
        └── screens/
```

### Where the interesting logic lives

Deliberately concentrated in three files, all free of I/O so they are testable
without a network or a database:

| File | Contains |
|---|---|
| `matcher.py` | `matches()` and `decide()` — when a notification fires. |
| `tgtg_source.py` | `normalize_item()` and `user_agent_for()` — parsing and identity. |
| `poller.py` | `Pacer` (via `tgtg_source`) — backoff behaviour. |

Everything else is plumbing.

---

## Setup

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Tests

```bash
.venv/bin/python -m pytest -q
```

82 tests, well under a second. Nothing touches the network — the TGTG client is
never constructed in a test.

| File | Covers |
|---|---|
| `test_matcher.py` | Matching rules and the alert decision table. |
| `test_normalize.py` | Response parsing across shapes, and UA precedence. |
| `test_pacer.py` | Backoff escalation and decay. |
| `test_api.py` | HTTP endpoints and the auth boundary. |
| `test_dev_mode.py` | Fixtures, failure simulation, config guards. |

**If you change when alerts fire, change `test_matcher.py` first.** It is the
part with real user consequences — waking a stranger at 21:40 for a bag that
resold out — and the parametrised cases exist to make the edge cases explicit.

---

## Dev mode

The alert path is otherwise close to untestable: the whole mechanism is a
0 → >0 stock transition, and you cannot make a real shop restock on demand. Dev
mode polls from a local JSON file instead, so you can flip a number and watch the
real matcher, the real database writes, and the real push fire.

### Setting it up

```bash
tgtg-alert dev fixture --write      # writes ./dev-fixture.json
```

Add to `.env`:

```bash
TGTG_DEV_MODE=1
TGTG_DEV_FIXTURE=/absolute/path/to/dev-fixture.json
TGTG_POLL_INTERVAL=20
```

Then `tgtg-alert serve`, and edit the fixture between polls.

### Driving a transition

The fixture ships with a Magic Bag at quantity 2. To watch an alert fire:

1. Set `"items_available": 0` on it. Wait for a poll — it is recorded as sold out.
2. Set it back to `3`. Wait for the next poll.

That is the `0 → >0` transition, and it should notify you:

```
INFO tgtg_alert.poller: alerted (restock): Magic Bag is back at Blank Street Coffee
```

Deleting the item entirely is equivalent to setting it to 0, which is how
absence-as-sold-out is verified.

### Testing failures

A `simulate` block makes the next fetch behave as if Too Good To Go refused it,
so you can exercise the backoff paths without waiting to actually get blocked:

```json
{
  "simulate": { "status": 403 },
  "items": []
}
```

| Value | Behaviour |
|---|---|
| `403` | Acts blocked by DataDome. Backoff escalates 1h → 2h → 4h → 6h. |
| `429` | Acts rate limited. Backoff 60s → 120s → … |
| anything else | Raised as a generic API error. |

Remove the block to resume.

### Guards

Two deliberate safety rails:

- **`TGTG_DEV_FIXTURE` without `TGTG_DEV_MODE` is a hard error.** The dangerous
  half-configuration is an operator believing they are on a fixture while the
  poller quietly talks to the live API.
- **The lowered poll floor requires a fixture**, not merely dev mode. Dev mode
  pointed at the live API keeps the production 300-second floor, because polling
  the real API every few seconds is exactly what gets accounts blocked.

Dev mode prints a banner at startup saying which of the two situations you are in:

```
*** DEV MODE: polling the fixture at /path/to/dev-fixture.json, NOT Too Good To Go. ***
```

### Fixture format

Either a bare list of items, or an object with an `items` key:

```json
{"items": [ ... ], "simulate": {"status": 403}}
```

Items use the same shape as the real API, and go through the same
`normalize_item()`, so a fixture exercises the real parsing path:

```json
{
  "item_id": "1001",
  "display_name": "Magic Bag",
  "items_available": 2,
  "price_including_taxes": {"code": "GBP", "minor_units": 399, "decimals": 2},
  "store": {"store_id": "s1", "store_name": "Blank Street Coffee", "distance": 450}
}
```

The file is re-read on **every** fetch, so edits take effect on the next poll and
a typo is reported immediately rather than silently cached.

`dev-fixture.json` is gitignored — it is scratch data, not project data.

---

## Why `tgtg` comes from git

`pyproject.toml` declares:

```
"tgtg @ git+https://github.com/ahivert/tgtg-python.git"
```

Not a version pin. The reason:

| Source | Item endpoint |
|---|---|
| PyPI `0.19.0` (2026-05-27) | `item/v8/` |
| git master (2026-06-08 onward) | `item/v9/` |

The bump to v9 landed **after** the last release. v8 is expected to stop
resolving, so the released package is a dependency with an expiry date.

The cost is that builds need `git` and network access. The Dockerfile handles it
in a builder stage. If PyPI ever catches up, switch to a version pin and delete
this section.

**Installing from git means you are tracking master**, so a `pip install -e .`
can pull in upstream changes. That is usually what you want here — it is a
fast-moving target — but it does mean builds are not reproducible. Pin a commit
if that matters to you.

---

## Extending

### Adding a notification channel

`notify.py` has the pattern. `WebhookNotifier` is the smallest example:

1. Take what you need in `__init__`.
2. Implement `send(tokens, title, body, *, collapse_key, data) -> PushResult`.
3. Never raise for a delivery failure — return a `PushResult` with `errors` set.
   The poller counts failures; a raise would abort the pass and lose the other
   watches' work.
4. Wire it in `Poller._dispatch()`, and add config in `config.py`.

Channels are attempted independently, so a webhook failure must not stop push.

### Adding a watch constraint

1. Add the column to the `watches` table in `db.py`. There is no migration
   system — new tables appear automatically via `CREATE TABLE IF NOT EXISTS`, but
   a new *column* on an existing table needs a manual `ALTER TABLE` for existing
   installs. Consider whether that is worth it.
2. Add the field to `WatchRule` in `matcher.py`.
3. Add the check to `matches()`.
4. Load and persist it in `poller.py` and `api.py`.
5. Test it in `test_matcher.py` — including that it combines with the others
   using AND.

### Changing when alerts fire

This is `decide()` in `matcher.py`, and it is the highest-consequence code in the
project. Read the docstring first — it explains why each rule exists, and most of
them are there to prevent a specific kind of noise.

Then **extend `test_matcher.py`**, do not just make the existing tests pass.

### The mobile app

```bash
cd mobile
npm install
npx tsc --noEmit          # typecheck
npx expo start            # dev server
npx expo export --platform android    # verify it bundles
```

`AGENTS.md` in `mobile/` has useful notes on Expo API drift — Expo renames
things between SDK releases, so check the versioned docs rather than assuming.

---

## Conventions

- **Comment the *why*, not the *what*.** The code says what it does. Comments
  exist for the reasoning that is not recoverable from reading it — why a
  constant is that value, why a guard is there, what breaks without it.
- **Tests do not touch the network.** If you need to exercise TGTG behaviour, use
  a fixture.
- **Failures in a pass are contained.** One bad watch or bucket must not lose the
  others' work.
- **Never raise for a delivery failure.** See the notifier contract above.

---

## Contributing

Before opening a PR:

```bash
cd server && .venv/bin/python -m pytest -q
cd ../mobile && npx tsc --noEmit
```

If you are fixing a Too Good To Go breakage, say which endpoint changed and how
you found out. That is the most perishable knowledge in the project.
