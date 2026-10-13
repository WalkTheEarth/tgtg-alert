"""Configuration, loaded from the environment with sane self-hosted defaults."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

# TGTG's anti-abuse is DataDome, and it responds to *frequency and consistency*
# rather than to a documented request quota. The community's most conservative
# deployed policy (the Home Assistant integration) uses a 60-minute baseline,
# dropping to ~3 minutes only inside known sales windows, with >=1s between
# calls. Our floor is deliberately well under that because a 60-minute poll
# would miss most drops, but the default is deliberately well above the
# "once a minute" range that maintainers report leads to IP bans.
MIN_POLL_INTERVAL_SECONDS = 300
DEFAULT_POLL_INTERVAL_SECONDS = 600

# Dev mode lowers the floor so you can iterate in seconds rather than minutes.
# It is only honoured when TGTG_DEV_MODE is on, and the poller says so loudly at
# startup, because a fast poll against the real API is how accounts get blocked.
DEV_MIN_POLL_INTERVAL_SECONDS = 10

# When DataDome blocks us we stop for this long and then resume at the slower
# cadence below, recovering gradually. The failure mode to design against is a
# tracker that looks healthy for 30 minutes and then silently dies on the first
# token refresh -- see `tgtg_source.classify_failure`.
BACKOFF_ON_BLOCK_SECONDS = 3600
BACKOFF_RECOVERY_POLLS = 6

# A modern TGTG Android user agent, used only when the live version cannot be
# determined. The library's built-in fallback is "24.11.0", roughly a year
# stale, and because every consumer of that library shares it, it is trivially
# fingerprintable -- which maintainers identify as the single most common cause
# of new 403s.
USER_AGENT_TEMPLATE = "TGTG/{} Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Pro Build/AP2A.240905.003)"

# Kept in sync with the template above; bump if the fallback ever needs moving.
DEFAULT_USER_AGENT = USER_AGENT_TEMPLATE.format("26.10.0")

# TGTG's own app refreshes its access token every 4h; match that.
ACCESS_TOKEN_LIFETIME_SECONDS = 3600 * 4


class ConfigError(ValueError):
    """A configuration problem the operator can fix.

    Its own type so the CLI can report it as a sentence rather than a traceback
    -- a misconfigured .env is a normal thing to hit, not a crash.
    """


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    data_dir: Path
    db_path: Path
    poll_interval: int
    host: str
    port: int
    api_token: str
    expo_access_token: str | None
    default_language: str
    request_timeout: float
    log_level: str
    # None means "not explicitly configured". That distinction matters: the
    # DataDome cookie is bound to whichever User-Agent solved the challenge, so
    # the same UA has to be used for login and for every later poll. An unset
    # value lets login resolve the current version once and store it.
    user_agent: str | None
    # Development affordances. See docs/development.md#dev-mode.
    dev_mode: bool
    dev_fixture: Path | None

    @classmethod
    def from_env(cls) -> "Config":
        dev_mode = _env_bool("TGTG_DEV_MODE")
        fixture_raw = os.environ.get("TGTG_DEV_FIXTURE", "").strip()
        dev_fixture = Path(fixture_raw).expanduser().resolve() if fixture_raw else None
        if dev_fixture and not dev_mode:
            # Refuse the half-configured case rather than silently polling the
            # live API while the operator believes they are on a fixture.
            raise ConfigError(
                "TGTG_DEV_FIXTURE is set but TGTG_DEV_MODE is not.\n"
                "Set TGTG_DEV_MODE=1 to use a fixture, or unset TGTG_DEV_FIXTURE."
            )

        data_dir = Path(os.environ.get("TGTG_DATA_DIR", "./data")).expanduser().resolve()
        poll_interval = _env_int("TGTG_POLL_INTERVAL", DEFAULT_POLL_INTERVAL_SECONDS)
        # Only a fixture makes a fast poll harmless. Dev mode pointed at the
        # live API keeps the production floor, because polling the real API
        # every few seconds is exactly the behaviour that gets accounts blocked.
        floor = (
            DEV_MIN_POLL_INTERVAL_SECONDS
            if (dev_mode and dev_fixture)
            else MIN_POLL_INTERVAL_SECONDS
        )
        if poll_interval < floor:
            poll_interval = floor

        api_token = os.environ.get("TGTG_API_TOKEN", "").strip()
        if not api_token:
            # A self-hosted box still needs *some* shared secret, otherwise
            # anyone who finds the port can read watch rules and push spam to
            # the paired phone. Generated per-process when unset; `tgtg-alert
            # init` writes a stable one into the env file.
            api_token = secrets.token_urlsafe(32)

        return cls(
            data_dir=data_dir,
            db_path=data_dir / "tgtg_alert.db",
            poll_interval=poll_interval,
            host=os.environ.get("TGTG_HOST", "0.0.0.0"),
            port=_env_int("TGTG_PORT", 8787),
            api_token=api_token,
            expo_access_token=os.environ.get("EXPO_ACCESS_TOKEN") or None,
            default_language=os.environ.get("TGTG_LANGUAGE", "en-GB"),
            request_timeout=_env_float("TGTG_HTTP_TIMEOUT", 20.0),
            log_level=os.environ.get("TGTG_LOG_LEVEL", "INFO").upper(),
            user_agent=os.environ.get("TGTG_USER_AGENT", "").strip() or None,
            dev_mode=dev_mode,
            dev_fixture=dev_fixture,
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
