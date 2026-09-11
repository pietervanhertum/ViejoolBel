"""Background health monitor.

Runs in its own thread and, on each tick:

* pets the systemd watchdog (so a hung app is restarted — NFR-2),
* periodically evaluates :mod:`viejoolbel.health`,
* sends a webhook alert when health transitions into a fault (and a recovery
  notice when it clears),
* sends a heartbeat ping while healthy (dead-man's-switch),
* keeps the latest report available for the web UI (``/api/health``).

Notification targets are read from the settings table (UI-editable), falling back
to the values in :class:`~viejoolbel.config.Settings`.
"""

from __future__ import annotations

import datetime as dt
import logging
import socket
import threading
import time
from zoneinfo import ZoneInfo

from . import ap, health, systemd_notify, wifi
from .config import Settings
from .db import get_setting, record_event, session_scope
from .health import HealthReport, Level
from .models import (
    EV_AP_FALLBACK,
    EV_HEALTH_FAULT,
    EV_HEALTH_RECOVERED,
    EV_SERVICE_STARTED,
)
from .notify import Notifier

log = logging.getLogger(__name__)


def _uptime_seconds() -> float | None:
    """Seconds since the machine booted (Linux /proc/uptime), or None off-device.

    Lets the startup notice tell a full reboot (small uptime) apart from a mere
    service restart (large uptime) — useful given the self-heal recovery reboot."""
    try:
        with open("/proc/uptime") as f:  # noqa: PTH123 - /proc is not a real path
            return float(f.read().split()[0])
    except (OSError, ValueError):
        return None


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}u {minutes}m"
    if hours:
        return f"{hours}u {minutes}m"
    return f"{minutes}m"


def _local_ip() -> str | None:
    """Best-effort primary LAN IP (no packets are actually sent), or None."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: just picks the outbound route
            return str(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        return None


class HealthMonitor:
    def __init__(
        self,
        settings: Settings,
        *,
        scheduler_is_alive,  # callable[[], bool]
        notifier: Notifier | None = None,
    ) -> None:
        self._settings = settings
        self._tz = ZoneInfo(settings.timezone)
        self._scheduler_is_alive = scheduler_is_alive
        self._notifier = notifier or Notifier()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="health-monitor", daemon=True)
        self._last_report: HealthReport | None = None
        self._last_level = Level.OK
        self._lock = threading.Lock()
        # Offline safety-net state.
        self._offline_since: float | None = None
        self._fallback_engaged = False

    @property
    def last_report(self) -> HealthReport | None:
        with self._lock:
            return self._last_report

    def start(self) -> None:
        systemd_notify.ready()
        # Announce startup from a throwaway thread so gathering WiFi/IP info and
        # posting the webhook (each can take seconds) never delays the first
        # watchdog pet in the monitor loop.
        threading.Thread(
            target=self._startup_notice, name="startup-notice", daemon=True
        ).start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # --- config helpers (UI-editable, env fallback) ----------------------
    def _webhook_url(self) -> str:
        with session_scope() as s:
            return get_setting(s, "notify_webhook_url", self._settings.notify_webhook_url)

    def _heartbeat_url(self) -> str:
        with session_scope() as s:
            return get_setting(s, "heartbeat_url", self._settings.heartbeat_url)

    def _notify_on_start(self) -> bool:
        with session_scope() as s:
            raw = get_setting(
                s, "notify_on_start", "1" if self._settings.notify_on_start else "0"
            )
        return raw not in ("0", "false", "False", "")

    # --- startup notice --------------------------------------------------
    def _startup_notice(self) -> None:
        """Record a durable 'started' event and, if enabled, POST an info webhook
        with the time, uptime and connected WiFi network. Best-effort throughout."""
        from . import __version__

        now = dt.datetime.now(self._tz)
        try:
            ssid = wifi.current_ssid()
        except Exception:  # never let the notice thread die
            log.exception("Startup notice: SSID lookup failed")
            ssid = None
        ip = _local_ip()
        uptime = _uptime_seconds()

        parts = [f"versie {__version__}", f"gestart {now:%Y-%m-%d %H:%M:%S %Z}"]
        if uptime is not None:
            parts.append(f"sinds boot: {_fmt_duration(uptime)}")
        parts.append(f"WiFi: {ssid or 'niet verbonden'}")
        if ip:
            parts.append(f"IP: {ip}")
        message = " · ".join(parts)

        try:
            with session_scope() as s:
                record_event(s, EV_SERVICE_STARTED, message, level="info")
        except Exception:
            log.exception("Startup notice: recording event failed")

        if not self._notify_on_start():
            return
        url = self._webhook_url()
        if url:
            self._notifier.alert(
                url,
                level="info",
                title="ViejoolBel gestart",
                message=message,
                tags="information_source",
            )

    # --- main loop -------------------------------------------------------
    def _loop(self) -> None:
        tick = self._settings.monitor_tick_seconds
        since_health = 1e9  # force an immediate evaluation on first tick
        since_heartbeat = 1e9
        while not self._stop.is_set():
            systemd_notify.watchdog()
            since_health += tick
            since_heartbeat += tick

            try:
                self._check_network_fallback()
            except Exception:  # the monitor must never die
                log.exception("Network fallback check failed")

            if since_health >= self._settings.health_interval_seconds:
                since_health = 0.0
                try:
                    self.evaluate_once()
                except Exception:  # the monitor must never die
                    log.exception("Health evaluation failed")

            if since_heartbeat >= self._settings.heartbeat_interval_seconds:
                since_heartbeat = 0.0
                report = self.last_report
                if report is not None and report.ok:
                    self._notifier.heartbeat(self._heartbeat_url())

            self._stop.wait(tick)

    # --- offline safety net ---------------------------------------------
    def _ap_fallback_minutes(self) -> int:
        with session_scope() as s:
            raw = get_setting(s, "ap_fallback_minutes", str(self._settings.ap_fallback_minutes))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return self._settings.ap_fallback_minutes

    def _ap_fallback_recovery_minutes(self) -> int:
        with session_scope() as s:
            raw = get_setting(
                s,
                "ap_fallback_recovery_minutes",
                str(self._settings.ap_fallback_recovery_minutes),
            )
        try:
            return int(raw)
        except (TypeError, ValueError):
            return self._settings.ap_fallback_recovery_minutes

    def _check_network_fallback(self) -> None:
        """If the device has had no network for the configured grace period, open
        the onboarding AP so it can be recovered on-site. A short blip resets the
        timer, so a router reboot or brief hiccup never triggers it; and once the
        AP is up we stand down (it blocks WiFi, so re-checking would just loop)."""
        minutes = self._ap_fallback_minutes()
        if minutes <= 0:  # disabled
            self._offline_since = None
            return
        if ap.network_online():
            self._offline_since = None
            self._fallback_engaged = False
            return
        # Offline. If the fallback AP (or an AP test) is already up, stand down.
        if ap.ap_is_active():
            self._fallback_engaged = True
            return
        now = time.monotonic()
        if self._offline_since is None:
            self._offline_since = now
            return
        if not self._fallback_engaged and (now - self._offline_since) >= minutes * 60:
            recovery = self._ap_fallback_recovery_minutes()
            log.warning(
                "No network for %d min; opening onboarding AP (safety net); "
                "auto-reboot in %s.",
                minutes,
                f"{recovery} min" if recovery > 0 else "off",
            )
            self._fallback_engaged = True
            recovery_note = (
                f" Het toestel herstart automatisch na {recovery} min om opnieuw "
                "verbinding te maken."
                if recovery > 0
                else ""
            )
            message = (
                f"Geen netwerk sinds {minutes} min. Het onboarding-netwerk "
                f"'{ap.AP_SSID}' is geopend zodat het toestel ter plaatse hersteld "
                f"kan worden.{recovery_note}"
            )
            # Persist the event and fire the alert BEFORE the radio is reconfigured:
            # once the AP takes over wlan0 the device is offline, so a webhook sent
            # afterwards would never leave. (The heartbeat dead-man's-switch is what
            # reliably catches the outage that follows.)
            with session_scope() as s:
                record_event(s, EV_AP_FALLBACK, message, level="warn")
            url = self._webhook_url()
            if url:
                self._notifier.alert(
                    url,
                    level="warning",
                    title="ViejoolBel: geen netwerk",
                    message=message,
                )
            ap.raise_ap(self._settings.ap_control_script, recovery)

    def evaluate_once(self) -> HealthReport:
        """Evaluate health, store it, and fire alerts on state transitions.
        Exposed so it can be called directly from the API and from tests."""
        now = dt.datetime.now(self._tz)
        with session_scope() as s:
            report = health.evaluate(
                s,
                now=now,
                data_dir=self._settings.data_dir,
                scheduler_alive=bool(self._scheduler_is_alive()),
                min_year=self._settings.min_plausible_year,
            )
        systemd_notify.status(f"health={report.level.value}")
        self._handle_transition(report)
        with self._lock:
            self._last_report = report
        return report

    def _handle_transition(self, report: HealthReport) -> None:
        prev, now_level = self._last_level, report.level
        if now_level is prev:
            return
        self._last_level = now_level
        if now_level is Level.OK:
            message = "Alle controles zijn OK."
            with session_scope() as s:
                record_event(s, EV_HEALTH_RECOVERED, message, level="ok")
        else:
            message = (
                "; ".join(f"{c.name}: {c.detail}" for c in report.problems)
                or "Onbekend probleem"
            )
            with session_scope() as s:
                record_event(s, EV_HEALTH_FAULT, message, level=now_level.value)
        url = self._webhook_url()
        if not url:
            return
        if now_level is Level.OK:
            self._notifier.alert(
                url, level="ok", title="ViejoolBel hersteld", message=message
            )
        else:
            self._notifier.alert(
                url,
                level=now_level.value,
                title=f"ViejoolBel probleem ({now_level.value})",
                message=message,
            )
