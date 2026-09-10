# Headless onboarding (no internet required)

Goal: bring a fresh device online at a school **without a screen, keyboard, or any
existing internet** (FR-19).

There are two paths, and you should prefer the first whenever you can:

1. **Preseed the WiFi before you ship it (zero-touch).** If you already know the
   school's WiFi, store it on the device *before* it leaves your hands. It then
   joins that network by itself on power-up and nobody on-site has to configure
   anything — they just plug it in. See **[Preseeding WiFi](#preseeding-wifi)**.
2. **On-site access-point onboarding (fallback).** If the WiFi isn't known in
   advance (or changes), the device brings up its own `ViejoolBel-Setup` network
   and someone at the school types the WiFi into a captive portal. See
   **[Access-point onboarding](#access-point-onboarding)**.

The installer enables the fallback automatically, so path 2 is always there as a
safety net even when you use path 1.

## Preseeding WiFi

Do this while you prepare the device at home/office — **not** at the school. The
network doesn't have to be in range: the profile is stored and used the moment
that SSID appears. Run [`deploy/preseed_wifi.sh`](../deploy/preseed_wifi.sh) once
per network:

```bash
# The school's WiFi (higher priority = preferred when both are in range):
sudo ./deploy/preseed_wifi.sh "SchoolWiFi" "the-school-password" 10

# Optional: your own bench WiFi, so you can finish setup/testing at home too:
sudo ./deploy/preseed_wifi.sh "WerkbankAP" "your-test-password" 1
```

Because it saves *multiple* networks, the same SD card works on your bench **and**
at the school — it connects to whichever is in range. When the device arrives at
the school it joins the school WiFi on its own and is reachable at
`viejoolbel.local`; the setup portal below never has to appear.

> Alternatively, Raspberry Pi Imager can preset a single WiFi network when you
> flash the card. That works too, but `preseed_wifi.sh` lets you save several
> networks and set which one wins, and you can run it on an already-prepared card.

## Access-point onboarding

Use this only when the WiFi wasn't preseeded. The installer enables it for you;
this is what happens on-site.

## How it works
At boot a small service (`viejoolbel-ap.service`) waits ~45 s for the Pi to join a
known WiFi network. If none is found it reconfigures `wlan0` as its own access
point and starts `hostapd` + `dnsmasq`:

- SSID **`ViejoolBel-Setup`** (password on the device label; default `belsetup2025`).
- The Pi is at **192.168.4.1**; the captive DNS points every hostname there, so any
  browser you open lands on the setup page.

Connect a phone/laptop to that network, open `http://192.168.4.1:8080`, and enter
the school's WiFi SSID + password. The device joins that network, tears the AP
down, and is then reachable at `viejoolbel.local`.

## Enabling the AP service
`deploy/install.sh` already installs and enables this unit for you (and masks the
packaged `hostapd`/`dnsmasq` services so they don't fight NetworkManager). You only
need the steps below to enable it by hand on a device installed before this was
automatic:

```bash
sudo cp deploy/ap-onboarding/viejoolbel-ap.service /etc/systemd/system/
sudo systemctl enable viejoolbel-ap.service
```

Example unit (`deploy/ap-onboarding/viejoolbel-ap.service`):

```ini
[Unit]
Description=ViejoolBel onboarding access point
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/viejoolbel/current/deploy/ap-onboarding/viejoolbel-ap.sh 45
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

## Changing WiFi later (from the web UI)
Once the device is reachable, WiFi is also manageable from **Instellingen → WiFi**:
it shows the current network, scans for nearby networks (signal strength, a lock
icon for secured ones), and lets you pick one and enter its password. This is the
same mechanism as the portal above (`set_wifi.sh`), handy when the school's WiFi
changes. Note that switching to a different network briefly drops the page; the
device is then reachable again at `viejoolbel.local`.

## Discovering the device on a LAN
Once on the school WiFi, the device advertises itself via mDNS/Avahi as
`viejoolbel.local`. If mDNS is blocked, find its IP from the router or via the
Tailscale admin console (see [`remote-support.md`](remote-support.md)).
