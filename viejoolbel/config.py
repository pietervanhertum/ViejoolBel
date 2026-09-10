"""Application configuration.

Settings come from environment variables (prefixed ``VIEJOOLBEL_``) so the same
code runs on a laptop (mock hardware, temp data dir) and on the Pi (real GPIO,
``/var/lib/viejoolbel``) without code changes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIEJOOLBEL_", env_file=".env", extra="ignore")

    # --- Storage ---
    data_dir: Path = Field(
        default=Path("/var/lib/viejoolbel"),
        description="Directory for the SQLite database and uploaded sounds.",
    )

    # --- Web server ---
    host: str = "0.0.0.0"
    port: int = 8080
    # Secret used to sign session cookies. MUST be overridden in production;
    # the installer generates a random one.
    secret_key: str = "dev-insecure-change-me"

    # --- Localisation ---
    timezone: str = "Europe/Brussels"

    # --- Hardware selection: "auto" | "gpio" | "mock" ---
    hardware: str = "auto"

    # --- GPIO pin map (BCM numbering). Documented in docs/hardware.md ---
    gpio_relay_pin: int = 17
    gpio_amp_enable_pin: int = 27
    gpio_button_pin: int = 22
    gpio_led_pin: int = 23
    # Seconds to power the amplifier before/after audio playback (anti-hum).
    amp_warmup_seconds: float = 1.0

    # --- Updates ---
    update_repo: str = "https://github.com/pietervanhertum/ViejoolBel"
    # Where releases are checked out; the "current" symlink points at the active one.
    releases_dir: Path = Field(default=Path("/opt/viejoolbel/releases"))
    # Privileged helper that performs the atomic swap + rollback (see updater.py).
    update_script: Path = Field(default=Path("/opt/viejoolbel/current/deploy/apply_update.sh"))
    # Privileged helper that joins a WiFi network + tears down the onboarding AP
    # (see wifi.py). Invoked via the scoped sudoers rule.
    wifi_script: Path = Field(default=Path("/opt/viejoolbel/current/deploy/set_wifi.sh"))
    # Privileged helper that forgets (deletes) a saved WiFi profile (see wifi.py).
    wifi_forget_script: Path = Field(
        default=Path("/opt/viejoolbel/current/deploy/forget_wifi.sh")
    )
    # Optional GitHub token (read-only) so the update check + clone work on a
    # PRIVATE repository. Stored in /etc/viejoolbel/viejoolbel.env. See
    # docs/github-auth.md.
    github_token: str = ""

    # --- Health monitoring & alerting ---
    # How often the monitor evaluates health and pings the systemd watchdog (s).
    monitor_tick_seconds: float = 10.0
    # How often a full health evaluation runs (s).
    health_interval_seconds: float = 60.0
    # Generic outbound webhook for fault alerts (ntfy.sh, Discord, Slack, Home
    # Assistant, custom). Empty = disabled. Can also be set from the web UI.
    notify_webhook_url: str = ""
    # Optional "dead man's switch": the device pings this URL periodically while
    # healthy (e.g. healthchecks.io). If pings stop, that service alerts you —
    # this is what catches a device that is fully offline or powered down.
    heartbeat_url: str = ""
    heartbeat_interval_seconds: float = 900.0
    # Minimum plausible year; a system clock below this means the clock is unset
    # (no RTC, no NTP) and rings would be wrong (see docs/hardware.md).
    min_plausible_year: int = 2024

    @property
    def db_path(self) -> Path:
        return self.data_dir / "viejoolbel.db"

    @property
    def sounds_dir(self) -> Path:
        return self.data_dir / "sounds"

    @property
    def update_log(self) -> Path:
        return self.data_dir / "update.log"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sounds_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
