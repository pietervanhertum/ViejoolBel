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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "viejoolbel.db"

    @property
    def sounds_dir(self) -> Path:
        return self.data_dir / "sounds"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sounds_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
