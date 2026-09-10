# Changelog

All notable changes to ViejoolBel are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.2.6] - 2026-09-10

### Added
- **WiFi diagnose (voor support).** A collapsible "Diagnose" section under WiFi in
  Instellingen shows the device's raw `nmcli` output — version, radio state,
  device status, rescan result, and the network list **with the FREQ/band column**
  — run as the app's own account. It makes clear why a scan finds nothing
  (a 2.4 GHz-only radio that cannot see 5 GHz networks, or an authorisation error)
  so it can be diagnosed without shell access. Backed by
  `GET /api/wifi/diagnostics`.

## [0.2.5] - 2026-09-10

### Fixed
- **You could forget the network the device was connected to — and strand it.**
  The saved-networks list showed a Vergeten button on the active connection;
  deleting it dropped the device off WiFi and removed the profile, so it did not
  reconnect on reboot. `forget()` now refuses to delete the active connection
  (with a clear message), and the UI shows "in gebruik" instead of a button for
  it.
- **A failed WiFi switch could leave the device offline.** `set_wifi.sh` now
  remembers the WiFi connection in use and, if joining the new network fails,
  reactivates the previous one so the device stays reachable.

## [0.2.4] - 2026-09-10

### Changed
- **WiFi is now managed the standard way — through NetworkManager, authorised by
  a polkit rule.** The app runs as an unprivileged service account, which
  NetworkManager otherwise only hands cached scan results (usually just the
  connected AP) while refusing connection changes — so the picker looked empty
  and "forget" failed with a sudo password prompt. A polkit rule
  (`deploy/polkit/10-viejoolbel-networkmanager.rules`, installed by `install.sh`
  and refreshed on update) grants the service account NetworkManager access, so
  `nmcli` scan / connect / delete work directly. Forgetting a network no longer
  goes through a sudo helper (`forget_wifi.sh` and its sudoers rule are removed).
- **A clearer WiFi picker.** The dropdown is replaced by an OS-style list of
  nearby networks — signal strength and a lock icon per row, the connected one
  marked — where selecting a secured network reveals an inline password field and
  a Verbind button. A "Verborgen netwerk…" option adds a network by name, and the
  saved-networks list keeps its per-network Vergeten button.

### Added
- **WiFi selection and login in Instellingen.** The settings page now shows the
  network the device is on, scans for nearby WiFi (signal strength, lock icon for
  secured networks), and lets you join one by picking it and entering the
  password — the same flow the onboarding portal uses, now available any time the
  network changes. Backed by `GET /api/wifi/scan`, `GET /api/wifi/status` and
  `POST /api/wifi/connect` (new `viejoolbel/wifi.py`), which reuse the existing
  scoped `set_wifi.sh` sudoers rule and degrade cleanly on a non-Pi machine.
- **Saved WiFi networks are listed and manageable in Instellingen.** A new list
  under WiFi shows every network the device remembers (added by connecting, or
  ahead of time by `preseed_wifi.sh`), marks the active one, and lets you forget
  one you no longer need. Backed by `GET /api/wifi/saved` and
  `POST /api/wifi/forget`, with a new scoped `forget_wifi.sh` sudoers rule for the
  privileged delete.

### Fixed
- **The WiFi scan still showed only the connected network.** `nmcli device wifi
  list --rescan yes` is all-or-nothing: when NetworkManager refuses the rescan
  (it rate-limits them, e.g. right after connecting) the whole call fails and the
  code fell back to the stale cache — which usually holds just the connected AP.
  The rescan is now triggered on its own (a refusal is ignored) and the list is
  read afterwards, with a short wait and re-read when the first read is still
  sparse, so nearby networks actually appear.
- **Forgetting a saved network failed with a raw `sudo: a password is required`
  error** when the device had not yet refreshed its sudoers rule for the new
  `forget_wifi.sh` helper. The WiFi actions now detect that specific sudo failure
  and show an actionable message (update the device, or re-run `install.sh`)
  instead of the cryptic sudo output.

## [0.2.0] - 2026-09-09

### Fixed
- **The update button now works.** The systemd unit set `NoNewPrivileges=true`,
  which propagates to child processes and blocks setuid binaries — so the
  sudo-based updater failed with *"the 'no new privileges' flag is set"* and the
  update did nothing. The flag is removed; privilege is still tightly scoped by
  the exact-command sudoers allowlist.
- **The overview date/day is in Dutch.** It was rendered with `strftime('%A')`,
  which uses the server's C locale and so always printed an English weekday
  (e.g. "Wednesday") on every device. It now reads e.g.
  *"woensdag 9 september 2026 — 17:30"* via explicit Dutch date helpers, with no
  dependency on a system `nl_NL` locale being installed.

### Changed
- **Updates now also refresh the systemd unit and sudoers rule.**
  `apply_update.sh` re-installs `deploy/systemd/viejoolbel.service` and
  `deploy/sudoers.d/viejoolbel` from the new release (with rollback), so
  deployment-config fixes reach devices through the normal update, instead of
  needing a manual `install.sh` re-run.

### Notes
- App-rendered times are 24-hour throughout. The bell-time editor keeps the
  native time picker (`<input type="time">`); its 12h/24h *display* follows the
  device's own language (a page cannot override it), while the value it stores is
  always 24-hour `HH:MM`. Set the device/browser language to Dutch for a 24-hour
  picker.

## [0.1.7] - 2026-09-09

### Added
- **Relay master switch** in Instellingen. Schools that only ring through the
  speaker can turn the relay off; when disabled it is hidden everywhere (Bel nu,
  the schedule editor and today's plan) and is never energised, whatever an event
  or caller requests.
- **Default bell** in Geluiden. Mark one sound as the default; it is used by the
  physical button on the device and is pre-selected in "Bel nu". Deleting the
  default clears the setting.

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
