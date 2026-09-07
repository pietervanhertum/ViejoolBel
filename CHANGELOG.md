# Changelog

All notable changes to ViejoolBel are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.1] - 2026-09-07

Initial release of the modern, calendar-aware school bell system, with the
first round of field fixes.

### Fixed
- Form buttons (Bel nu, and every other AJAX form) no longer navigate to the raw
  JSON API response. `postForm` was `async`, so `onsubmit="return postForm(this)"`
  returned a truthy Promise and the browser also submitted the form natively (and
  fired the request twice — the second hitting the ring lock and returning
  `{"ok":false}`). `postForm` is now synchronous and returns `false`, cancelling
  the native submit; the request runs in the background.

### Added
- Calendar-aware scheduling: weekly timetable, multiple day-types, and a
  holiday/exception calendar with deterministic, unit-tested resolution.
- Hardware abstraction with a real Raspberry Pi driver (GPIO relay +
  amplifier-enable + status LED + button, audio via `ffplay`/`aplay`) and a mock
  driver so the whole app runs and is tested off-device.
- Single, lock-guarded ring path with an audit log; scheduled/manual/button/test
  rings can never overlap.
- **Default collection of bell sounds** (Enkele bel, Dubbele bel, Schoolbel,
  Gong) — original synthesized WAVs bundled in the package and installed on first
  run, so the bell works out of the box with no uploads. Regenerate with
  `scripts/generate_default_sounds.py`.
- FastAPI web interface + JSON API: login, dashboard, ring-now, self-test,
  silence-today, sound upload, day-type/event and calendar CRUD, backup, password
  change.
- **Full branded management UI** (Basisschool de Viejool, Eksel): a consistent
  design system with pages for Overzicht, Roosters (day-types + weekly layout,
  inline bell-time editing), Kalender (month view with holidays/exceptions),
  Geluiden (upload/preview/delete), and Instellingen (password, volume,
  notifications, backup). Backed by new endpoints for renaming/deleting/defaulting
  day-types, editing events, weekday defaults, calendar listing/deletion/month
  resolution, settings, and sound preview.
- APScheduler-based scheduler that plans precise ring jobs per day (no 1 Hz
  polling) and re-plans on config change and daily.
- Safe self-updater design with atomic release swap and automatic rollback,
  **wired end-to-end**: Instellingen has a "Zoek naar updates" / "Installeer"
  flow backed by `GET /api/update/check` and `POST /api/update/apply`. Apply is
  launched detached (survives the service restart), validates the version tag,
  and fails gracefully off-device. Publishing guide in `docs/updates.md`.
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
