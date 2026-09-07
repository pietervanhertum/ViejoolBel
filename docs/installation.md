# Installation

## 1. Flash the SD card
Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In the imager's
settings you can pre-set the hostname (`viejoolbel`), enable SSH, and enter WiFi —
handy, but ViejoolBel can also onboard WiFi later with no internet (see
[`onboarding.md`](onboarding.md)).

## 2. Install
Boot the Pi, then:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/pietervanhertum/ViejoolBel
cd ViejoolBel
sudo ./deploy/install.sh
```

The installer:
- installs OS packages (`python3-venv`, `ffmpeg`, `alsa-utils`, `avahi-daemon`, …),
- creates the unprivileged `viejoolbel` service user,
- lays the release out under `/opt/viejoolbel/releases/<version>` with a `current`
  symlink,
- creates a virtualenv and installs the app (with the `pi` extra for `RPi.GPIO`),
- generates a random session secret in `/etc/viejoolbel/viejoolbel.env`,
- installs and starts the `viejoolbel` systemd service.

## 3. First login
Browse to `http://viejoolbel.local:8080` (mDNS) or the Pi's IP. Log in with
`admin` / `changeme` and **change the password immediately** (the dashboard nags
until you do).

## 4. Recommended next steps
- Add the DS3231 RTC (see [`hardware.md`](hardware.md)).
- Enable remote support (see [`remote-support.md`](remote-support.md)).
- Upload your bell sounds and build your weekly schedule and holiday calendar.

## Operating
```bash
journalctl -u viejoolbel -f        # live logs
sudo systemctl restart viejoolbel  # restart
```

## Updating
Use the update button in the web UI, or from a shell:
```bash
sudo /opt/viejoolbel/current/deploy/apply_update.sh v0.2.0
```
Updates are atomic and roll back automatically if the new version is unhealthy.
