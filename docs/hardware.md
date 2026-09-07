# Hardware

ViejoolBel drives the bell in two independent ways; use either or both.

## Bill of materials

| Part | Notes |
|---|---|
| Raspberry Pi (3/4/Zero 2 W) | Zero 2 W is enough; WiFi built in. |
| microSD card (16 GB+) | Raspberry Pi OS Lite (64-bit). |
| **DS3231 RTC module** | **Strongly recommended.** Keeps time across power loss when offline. |
| Relay module (opto-isolated, 3.3 V logic) | To drive an existing electric bell. |
| Amplifier + loudspeaker (or powered speaker) | For audio bell sounds. |
| Amplifier-enable line (optional) | GPIO to power the amp only while ringing (anti-hum). |
| Momentary push button (optional) | Physical "ring now". |
| Status LED (optional) | Idle/ringing/error indicator. |

## GPIO pin map (BCM numbering)

These match the defaults in `viejoolbel/config.py`; override via environment
variables (`VIEJOOLBEL_GPIO_*`) if your wiring differs.

| Function | Env var | Default (BCM) |
|---|---|---|
| Relay (electric bell) | `VIEJOOLBEL_GPIO_RELAY_PIN` | 17 |
| Amplifier enable | `VIEJOOLBEL_GPIO_AMP_ENABLE_PIN` | 27 |
| Push button | `VIEJOOLBEL_GPIO_BUTTON_PIN` | 22 |
| Status LED | `VIEJOOLBEL_GPIO_LED_PIN` | 23 |

The button is wired active-low to GND (internal pull-up is enabled). The relay and
amp-enable lines are active-high.

## Safety

- **The mains side of the school bell must be switched by a properly rated relay
  or contactor and installed by a qualified electrician.** The Pi only provides a
  low-voltage control signal.
- Power the Pi from a good 5 V supply; brownouts corrupt SD cards. Consider a
  small UPS/battery hat for reliability.

## Real-time clock (why it matters)

The Raspberry Pi has **no battery-backed clock**. Without internet it forgets the
time on every power cut and would ring at the wrong moments. The DS3231 keeps
accurate time for years on a coin cell. Enable it on Raspberry Pi OS by adding
`dtoverlay=i2c-rtc,ds3231` to `/boot/firmware/config.txt` and enabling I²C; the
kernel then sets the system clock from the RTC at boot.
