# Changelog

All notable changes to ViejoolBel are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - unreleased

Initial foundation of the modern, calendar-aware school bell system.

### Added
- Calendar-aware scheduling: weekly timetable, multiple day-types, and a
  holiday/exception calendar with deterministic, unit-tested resolution.
- Hardware abstraction with a real Raspberry Pi driver (GPIO relay +
  amplifier-enable + status LED + button, audio via `ffplay`/`aplay`) and a mock
  driver so the whole app runs and is tested off-device.
- Single, lock-guarded ring path with an audit log; scheduled/manual/button/test
  rings can never overlap.
- FastAPI web interface + JSON API: login, dashboard, ring-now, self-test,
  silence-today, sound upload, day-type/event and calendar CRUD, backup, password
  change.
- APScheduler-based scheduler that plans precise ring jobs per day (no 1 Hz
  polling) and re-plans on config change and daily.
- Safe self-updater design with atomic release swap and automatic rollback.
- **Self-healing**: `Type=notify` systemd unit with a real watchdog (the app pets
  it from a health-monitor thread via `sd_notify`), `Restart=always`, and
  boot-time auto-start so the device recovers unattended after a power cut.
- **Fault reporting**: a health monitor evaluates clock/scheduler/rings/disk,
  sends a webhook alert on fault transitions (ntfy/Discord/Slack/custom), sends a
  heartbeat while healthy (dead-man's-switch), and shows status on the dashboard;
  `/api/health` and UI-editable notification settings included.
- Deployment: systemd unit (with watchdog + hardening), installer, scoped sudoers,
  privileged update helper, WiFi access-point onboarding, Tailscale remote support.
- Tests (pytest), linting (ruff), typing (mypy), and GitHub Actions CI.
- Design and specification documents plus hardware/installation/onboarding/
  remote-support guides, and **printable Dutch install + user guides**.
