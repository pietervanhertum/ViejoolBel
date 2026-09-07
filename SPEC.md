# ViejoolBel — Specification

Functional and non-functional requirements. Requirement IDs (`FR-x`, `NFR-x`) are
referenced from code and tests.

## 1. Actors
- **Admin** — installs, configures and remotely supports the device (you).
- **School staff** — day-to-day: ring now, silence today, minor timetable edits.
- **The device** — the Raspberry Pi running ViejoolBel.

## 2. Functional requirements

### Scheduling
- **FR-1** The system rings according to a **weekly timetable**.
- **FR-2** Multiple **day-types** are supported (e.g. Normal, Wednesday, Exam),
  each with its own ordered list of bell events.
- **FR-3** A **calendar** maps dates to day-types and marks **closed days**
  (holidays/vacations); on closed days nothing rings automatically.
- **FR-4** Calendar resolution is deterministic with a defined priority:
  explicit single-date override > date-range override > weekday default > global
  default day-type.
- **FR-5** Each **bell event** specifies: time-of-day, which **sound**, whether to
  use **audio**, whether to use the **relay**, and a **duration**.
- **FR-6** All scheduling is **timezone-aware**; DST transitions are handled.

### Sounds & output
- **FR-7** Admin can **upload, name, preview and delete** sound files.
- **FR-8** Output supports **audio (speaker/amplifier)** and **relay (electric
  bell)**, independently per event, and both together.
- **FR-9** A distinct **evacuation/alarm** sound can be triggered manually and
  runs until explicitly stopped.
- **FR-10** Optional **amplifier-enable** output powers the amp shortly before and
  after ringing (to avoid hum / pops).

### Manual control
- **FR-11** A **"Ring now"** action rings a chosen sound immediately.
- **FR-12** A **physical button** on the device rings the default sound.
- **FR-13** **"Silence today"** disables all automatic rings for the current day
  (e.g. field trip); it auto-clears at midnight.
- **FR-14** Rings are **mutually exclusive** (a hardware lock); a new ring while
  one is in progress is rejected or queued, never overlapped.

### Web interface
- **FR-15** All configuration is possible from a **mobile-friendly web UI** over
  WiFi.
- **FR-16** The UI shows **live status**: current time, next ring, today's
  resolved schedule, service/health, last rings.
- **FR-17** The UI is **password protected**.
- **FR-18** Admin can **export/import** the full configuration (backup/restore).

### Connectivity & lifecycle
- **FR-19** **Headless onboarding**: with no known WiFi the device exposes a WiFi
  AP + captive portal to set WiFi credentials, with no internet required.
- **FR-20** The device is discoverable on the LAN as `viejoolbel.local` (mDNS).
- **FR-21** **Remote support**: the admin can reach the UI and a shell from
  anywhere **without** changing the school's router/firewall (Tailscale).
- **FR-22** An **update** action pulls a new tagged release from the repository,
  applies it atomically and **rolls back** on failure.
- **FR-23** Time is synced via **NTP** when online; an **RTC** keeps time across
  power loss when offline.

### Observability
- **FR-24** Every ring (scheduled/manual/button/test) and every config change is
  recorded in an **audit log** viewable in the UI.
- **FR-25** A **self-test** verifies audio and relay output on demand.

## 3. Domain semantics
- A **DayResolution** for a date is either `CLOSED` or a `DayType`.
- A **BellEvent** time is local wall-clock time in the configured timezone.
- "Silence today" is an override evaluated at ring time, not baked into the
  calendar.

## 4. Non-functional requirements
- **NFR-1 Accuracy** — a scheduled bell fires within ±2 s of its wall-clock time
  under normal load.
- **NFR-2 Resilience** — survives power loss: on boot it resumes correctly; with an
  RTC it keeps correct time offline. `systemd` restarts the service on crash.
- **NFR-3 Safety** — invalid configuration can never be persisted; a failed update
  never leaves the device unbootable.
- **NFR-4 Security** — no unauthenticated control; least-privilege OS user;
  transport encryption for remote access.
- **NFR-5 Testability** — the full application runs and is tested without Pi
  hardware via the mock driver; CI is green with no hardware and no root.
- **NFR-6 Maintainability** — one service, one config store, documented install
  and update paths, typed and linted code.
- **NFR-7 Longevity** — supported Python (3.11+), no EOL dependencies (contrast
  with campanella's Python 2 / PHP).

## 5. Acceptance highlights (v0.1)
- Given a weekday mapped to a day-type with a bell event at `10:30`, when the clock
  reaches `10:30`, the bell rings once via the configured outputs. *(FR-1,5,14)*
- Given today is marked closed, no automatic ring occurs. *(FR-3)*
- Given "silence today" is on, no automatic ring occurs today, but "ring now"
  still works. *(FR-13,11)*
- The API rejects a bell event with a malformed time or unknown sound. *(NFR-3)*
- The whole suite passes on a laptop with `VIEJOOLBEL_HARDWARE=mock`. *(NFR-5)*
