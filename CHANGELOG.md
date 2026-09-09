# Changelog

All notable changes to ViejoolBel are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.6] - 2026-09-09

### Added
- **Zero-touch WiFi for devices you ship but don't install yourself.** A new
  `deploy/preseed_wifi.sh` stores one or more WiFi networks on the device before
  it leaves your hands, so it joins the site's WiFi automatically on power-up and
  nobody on-site has to use the setup portal — they just plug it in. Multiple
  networks can be saved with a priority, so the same card works on your bench and
  at the school. Documented in `docs/onboarding.md` and the printable Dutch
  install guide.

### Changed
- **The installer now enables the on-site onboarding portal automatically.**
  `deploy/install.sh` installs `hostapd`/`dnsmasq`, masks their packaged system
  services (so they don't fight NetworkManager), and enables
  `viejoolbel-ap.service` as an offline fallback. Preseeded WiFi still takes
  precedence; the portal only appears when no known network is joined.

### Fixed
- **A stale/expired GitHub token blocked the update check with HTTP 401**, even on
  a public repo (GitHub validates the token whenever one is sent). The check now
  retries anonymously when a token is rejected, so a leftover bad token no longer
  breaks updates on a public repository. The token is also whitespace-trimmed.
- **The device showed the code's `__version__` (e.g. 0.1.3) instead of the release
  it was actually running (e.g. v0.1.5)**, which also made the update check offer
  the same version in a loop. `apply_update.sh` now records the installed tag and
  the app reports that, so the displayed version matches the deployment and the
  update check compares tag-to-tag.
- **Default bell sounds were missing on devices first installed before the feature
  existed.** They were only seeded into a brand-new database. Seeding now runs once
  (guarded by a flag) and adds any missing defaults by name on upgrade, without
  touching the user's own uploads.

## [0.1.3] - 2026-09-09

### Fixed
- **A malformed line in the env file aborted every update.** `apply_update.sh`
  *sourced* `/etc/viejoolbel/viejoolbel.env` with bash, so a value bash could not
  source (e.g. a space after `=`, as in `VIEJOOLBEL_GITHUB_TOKEN= github_pat_…`)
  made bash try to run the token as a command ("command not found") and stopped
  the update before it began. The env file is now parsed safely with text tools
  (`deploy/lib_env.sh`), tolerant of surrounding whitespace and quotes, and is
  never executed.
- **The browser kept running the old JavaScript after an update**, so UI fixes
  (like "Bel nu" no longer navigating to the raw JSON) appeared to have no effect
  until a hard refresh. Static assets are now cache-busted per version
  (`/static/app.js?v=<version>`) and HTML pages send `Cache-Control: no-cache`, so
  a new version's JS/CSS is always fetched.
- **Software updates ran silently.** The apply script's output was sent to
  `/dev/null`, so a failed clone, a failed `pip install` (e.g. no internet), or a
  failed health check produced a "202 Accepted" and then nothing visible. Output
  is now captured to an update log (`<data_dir>/update.log`) and to journald
  (`journalctl -t viejoolbel-update`), pip errors are no longer discarded, and the
  script reports the failing step. A new **"Toon updatelog"** button and
  `GET /api/update/log` surface it in the web UI.

## [0.1.2] - 2026-09-07

### Changed
- **Usability polish for non-experts:** the default day-type is now named in Dutch
  ("Gewone dag" instead of "Normal"); every save shows a brief confirmation toast;
  "audio" / "relais" are explained inline (speaker vs. electric bell); and the
  advanced notification settings are labelled as optional.

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
