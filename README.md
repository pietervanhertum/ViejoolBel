# ViejoolBel

A modern, calendar-aware **school bell system** for the Raspberry Pi.

ViejoolBel rings a school's bell on a weekly timetable, plays configurable sounds
through a loudspeaker **and/or** drives an existing electric bell via a relay, and
is fully manageable from a phone or laptop over WiFi. It is designed to be
installed **headless** and supported **remotely** without ever touching the
school's network configuration.

The concept is inspired by [campanella](https://lizzit.it/campanella), but this is
a clean, tested, from-scratch implementation on a modern stack.

## Highlights

- 🔔 **Calendar-aware scheduling** — weekly timetable, multiple day-types
  (e.g. Wednesday schedule, week A/B), and a holiday/exception calendar so it
  stays silent on days off.
- 🎵 **Audio *and* relay output** — play sound files through a speaker/amplifier,
  drive a physical electric bell through a GPIO relay, or both. Different sounds
  per moment (start of day, break, end, evacuation alarm).
- 📱 **Web interface over WiFi** — set sounds and timings, ring the bell now,
  "silence today", see history. Password protected, served over HTTPS.
- 📡 **Headless onboarding** — with no known WiFi the Pi opens its own access
  point + captive portal so you can configure WiFi with no internet. Reachable at
  `viejoolbel.local` via mDNS.
- 🌐 **Remote support without network changes** — a [Tailscale](https://tailscale.com)
  mesh VPN lets you reach the device from anywhere, behind NAT/firewall, without
  port-forwarding or any change to the school's network.
- ⬆️ **Safe self-update** — an update button pulls a new tagged release from this
  repository, applies it atomically, and **rolls back automatically** if the new
  version fails its health check.
- 🧪 **Runs and is tested on any machine** — the hardware layer has a mock driver,
  so the whole system can be developed and tested without a Raspberry Pi.

## Documentation

| Document | Contents |
|---|---|
| [`DESIGN.md`](DESIGN.md) | Architecture, components, data flow, key decisions |
| [`SPEC.md`](SPEC.md) | Functional & non-functional requirements |
| [`docs/hardware.md`](docs/hardware.md) | Wiring, relay, amplifier, RTC, GPIO pinout |
| [`docs/installation.md`](docs/installation.md) | Flashing & installing on the Pi |
| [`docs/onboarding.md`](docs/onboarding.md) | Headless first-boot WiFi setup |
| [`docs/remote-support.md`](docs/remote-support.md) | Tailscale remote access |

## Quick start (development, no Raspberry Pi needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# Run against the mock hardware driver:
VIEJOOLBEL_HARDWARE=mock viejoolbel run
# Open http://127.0.0.1:8080  (default login: admin / changeme)
```

Run the test suite and linters:

```bash
pytest
ruff check .
mypy viejoolbel
```

## Install on a Raspberry Pi

See [`docs/installation.md`](docs/installation.md). In short:

```bash
git clone https://github.com/pietervanhertum/ViejoolBel
cd ViejoolBel
sudo ./deploy/install.sh
```

## License

MIT — see [`LICENSE`](LICENSE).
