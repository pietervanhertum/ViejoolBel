# Changelog

All notable changes to ViejoolBel are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.2] - 2026-09-07

### Fixed
- **Update check reported "up to date" for a valid newer release** when the
  release tag had unusual punctuation (e.g. `v.0.1.1`). Version parsing now
  extracts the numbers from a tag, tolerating prefixes and stray separators
  (`v0.1.1`, `0.1.1`, `v.0.1.1`, `release-0.1.1` all compare correctly), and the
  apply endpoint accepts any argv-safe tag containing a digit.
- **Un-ticking a checkbox (audio / relais) was ignored** everywhere. Unchecked
  checkboxes are omitted from a browser form post, so the server's `True` default
  won and audio/relay could never be turned off (Bel nu, and adding/editing bell
  events). The client now sends every checkbox as an explicit `true`/`false`.
- **The volume setting had no effect.** The audio player ignored `volume_db`; it
  is now applied via an ffplay `volume` filter.
- **Sound uploads could overwrite each other.** Filenames were derived from
  `hash(name) % N` (collision-prone) and written before the duplicate-name check.
  Uploads now use a unique filename and reject a duplicate name before writing.

### Added
- **Private-repository support for updates.** `check_latest` sends a
  `Bearer` token and `apply_update.sh` clones with it, read from
  `VIEJOOLBEL_GITHUB_TOKEN` in `/etc/viejoolbel/viejoolbel.env`, so both the
  update button and the CLI work on a private repo. See `docs/github-auth.md`.
- **Configuration restore (import)** completes backup/restore (FR-18). The backup
  is now a portable JSON document (day-types + events, weekly layout, calendar,
  settings) that references sounds and day-types by name; restore replaces the
  schedule configuration, keeps existing audio, matches sounds by name, and
  reports any events whose sound is missing (they become relay-only).

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
