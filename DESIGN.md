# ViejoolBel — Design

This document describes the architecture and the key engineering decisions. For
*what* the system must do, see [`SPEC.md`](SPEC.md).

## 1. Goals & constraints

- Runs unattended on a Raspberry Pi in a school for years.
- Must ring on time **even without internet** and survive power loss.
- Configured and supported by non-experts over WiFi; supported remotely by an
  admin who has **no access to the school's network configuration**.
- Safe to update in the field, with automatic rollback.
- Fully developable and testable **without** Raspberry Pi hardware.

## 2. High-level architecture

A single Python service, `viejoolbel`, runs under **systemd**. It hosts three
cooperating parts in one process:

```
                      ┌───────────────────────────────────────────┐
                      │              viejoolbel service            │
   Browser  ────────► │  ┌───────────┐   ┌────────────┐            │
   (WiFi / Tailscale) │  │  Web/API  │   │  Scheduler │            │
                      │  │ (FastAPI) │◄─►│ (APScheduler)│           │
                      │  └─────┬─────┘   └──────┬──────┘            │
                      │        │                │                   │
                      │        ▼                ▼                   │
                      │  ┌──────────────────────────────┐          │
                      │  │        Domain / Services       │         │
                      │  │  calendar · schedule · sounds  │         │
                      │  │  audit · updater · settings    │         │
                      │  └───────────────┬───────────────┘         │
                      │        ┌─────────┴─────────┐               │
                      │        ▼                   ▼               │
                      │  ┌───────────┐      ┌───────────────┐      │
                      │  │  Storage  │      │   Hardware    │      │
                      │  │ (SQLite)  │      │   driver      │      │
                      │  └───────────┘      └──────┬────────┘      │
                      └────────────────────────────┼──────────────┘
                                    GPIO relay ◄────┴────► audio out
                                    status LED           (speaker/amp)
                                    physical button
```

Why one process rather than campanella's daemon-plus-Apache-plus-PHP split:

- One thing to install, supervise, restart, watchdog and update.
- The web layer and the scheduler share the same validated config and the same
  hardware lock (no two things ringing at once).
- Simpler security surface (no PHP, no separate web server as root helpers).

## 3. Components

### 3.1 Storage (`viejoolbel/db.py`, `models.py`)
- **SQLite** via SQLAlchemy 2.0. One file, easy to back up, transactional.
- Schema is versioned; a tiny migration runner upgrades old databases on start.
- Sound files live on disk under a data directory; the DB stores metadata.

### 3.2 Domain model (see `SPEC.md` §3 for semantics)
- `Sound` — an uploaded audio file + display name + default duration.
- `DayType` — a named timetable (e.g. "Normal", "Wednesday", "Exam"). Contains
  ordered `BellEvent`s (time-of-day + which sound + relay on/off + duration).
- `CalendarRule` — maps concrete dates or weekdays to a `DayType`, or marks them
  as **closed** (holidays/vacations). Resolution order is defined in `calendar.py`.
- `RingLog` — every ring (scheduled, manual, test, button) with outcome.
- `Setting` — key/value app settings (timezone, volume, auth, amp warm-up, …).

### 3.3 Calendar resolution (`viejoolbel/calendar.py`)
Pure, deterministic function `resolve_day(date) -> DayResolution`. Given a date it
returns the effective `DayType` (or "closed") by applying rules in priority order:
explicit date override > date-range (vacation) > weekday default > global default.
It is pure (no I/O) so it is exhaustively unit-tested.

### 3.4 Scheduler (`viejoolbel/scheduler.py`)
- Uses **APScheduler**. Every day at 00:01 (and on startup, and whenever config
  changes) it computes today's ring events via the calendar and registers precise
  one-shot jobs. This is more robust and testable than campanella's 1 Hz polling
  loop and does not busy-wait.
- All actual ringing goes through a single `ring()` path that takes a hardware
  **lock**, so scheduled/manual/button rings can never overlap.
- Missed-ring policy: if the service was down at a ring time we **do not** replay
  it (a late bell is worse than none), but the gap is recorded in the audit log.

### 3.5 Hardware abstraction (`viejoolbel/hardware/`)
- `base.py` — `BellHardware` protocol: `ring(sound, duration, use_relay, use_audio)`,
  `set_status(state)`, `read_button()`, `self_test()`, `cleanup()`.
- `gpio_audio.py` — real driver: GPIO relay + status LED + button (RPi.GPIO),
  audio playback via `ffplay`/`aplay`, optional amplifier-enable GPIO with warm-up.
- `mock.py` — records calls in memory; used in dev and in **all** tests.
- The driver is selected at runtime by `VIEJOOLBEL_HARDWARE` (`auto`/`gpio`/`mock`).
  On non-Pi machines `auto` falls back to `mock`, so nothing is Pi-specific above
  this layer. This is what makes the whole system testable off-device.

### 3.6 Web / API (`viejoolbel/web/`)
- **FastAPI** app: JSON API + server-rendered Jinja pages, mobile-first.
- Session-cookie auth (single admin account; password hashed with bcrypt).
- Endpoints for schedule/day-type/calendar CRUD, sound upload, **ring now**,
  "silence today", status/health, history, settings, and **update**.
- Served over HTTPS with a self-signed cert generated on first boot (documented
  trade-off; Tailscale provides transport security for remote access).

### 3.7 Updater (`viejoolbel/updater.py`)
- The update button fetches the latest **tagged release** from this repository.
- Update is atomic: new version is checked out into a fresh directory, a health
  check runs, the systemd symlink is flipped, and the service restarts. If the new
  version fails to come up healthy, it **rolls back** to the previous release.
- The current version is never mutated in place, so a failed update cannot brick
  the device.

## 4. Networking & operations

### 4.1 Time (critical)
The Pi has **no real-time clock**. We:
- Sync via **NTP** whenever internet is available.
- Strongly recommend a **DS3231 RTC module** (see `docs/hardware.md`) so the clock
  survives power loss with no internet. Without it, a school with no internet and a
  power cut would ring at the wrong time.
- All scheduling is timezone-aware (default `Europe/Brussels`), so DST is handled.

### 4.2 Headless onboarding (no internet)
On boot, if no known WiFi network is joinable within a timeout, the Pi starts its
own WiFi access point + captive portal (`deploy/ap-onboarding/`). The admin
connects to it and enters the school's WiFi credentials. Also reachable at
`viejoolbel.local` (mDNS/Avahi). See `docs/onboarding.md`.

### 4.3 Remote support (no school-network changes)
[Tailscale](https://tailscale.com) creates an outbound, NAT-traversing mesh VPN.
The device dials out (port 41641/UDP, falls back to relays), so **no inbound ports
or firewall/router changes are needed at the school**. The admin reaches the web
UI and SSH over the tailnet from anywhere. See `docs/remote-support.md`.

## 5. Reliability & security

- systemd `Restart=on-failure` + `WatchdogSec`; the app pings the watchdog only
  while its main loop is healthy.
- Config is **validated** before it is persisted, so the UI cannot save a schedule
  that would crash the scheduler (a real weakness of campanella).
- Web UI requires authentication; runs as an unprivileged user; only the specific
  privileged actions (reboot, WiFi config) are allowed via tightly-scoped sudo.
- Every ring and every config change is written to an audit log.
- A **self-test** endpoint plays a short tone / pulses the relay so you can verify
  the speaker and amplifier actually work.

## 6. Testing strategy

- **Unit**: calendar resolution, schedule computation, config validation, updater
  logic (with fakes) — pure and fast.
- **Integration**: FastAPI `TestClient` against the mock hardware driver exercises
  the full API including ring-now and schedule CRUD.
- **CI**: GitHub Actions runs `ruff`, `mypy` and `pytest` on every push/PR.
- The mock hardware driver means CI needs no hardware and no root.

## 7. Explicitly out of scope for v0.1 (roadmap)
- Multi-site fleet management dashboard.
- Push/email alerting when the device is unreachable (needs an external relay).
- Zone/multi-speaker audio routing.
These are noted so the data model leaves room for them.
