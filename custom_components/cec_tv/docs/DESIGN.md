# CEC TV — design

Home Assistant integration that controls a TV over HDMI-CEC through the Kodi box
plugged into it, and shows the TV's **real** power state read over CEC.

## Why

A TV controlled over the network is invisible once it loses its network
connection: the home automation system neither knows it is on nor can switch it
off. CEC travels over the HDMI cable, so the Kodi box connected to the TV is a
control path that survives.

## Architecture

```
switch (this integration)
  --JSON-RPC--> Kodi --Addons.ExecuteAddon--> script.cec.control --CEC builtin--> TV
  <-JSON-RPC--- Kodi <--Window(Home) props--- script.cec.control service <--CEC-- TV
```

The integration depends on the Kodi addon
[`script.cec.control`](https://github.com/ikseth/kodi-addon-cec) **0.2.0 or later**:

- **Commands**: the addon runs Kodi's own CEC builtins (`CECActivateSource`,
  `CECStandby`). External processes cannot open the CEC adapter while Kodi holds
  it (`EBUSY`), so commands have to go through Kodi.
- **State**: a service in the addon asks the TV its power status over CEC every
  30 s (and in a burst after each command) and publishes it as `Window(Home)`
  properties (`cec.protocol`, `cec.tv_power`, `cec.tv_power_ts`, ...). This
  integration reads them with `XBMC.GetInfoLabels`.

No ports, credentials or code are added on the Kodi box beyond the addon. The
integration uses Kodi's existing web server (JSON-RPC) and its credentials.

## Entities
- 0.2.0 exposed `kodi_active_source` and `active_source` (addon 0.3.0). Removed in
  0.2.1: addon 0.3.1 stopped asking the bus for the active source, because with Kodi
  in front nobody answered and, after a TV woke up on its own, the query made Kodi
  claim the source and switch the TV input. Standby works whatever the TV shows:
  since addon 0.3.0 it is sent straight to the TV over the kernel CEC API, because
  Kodi's `CECStandby` only acts when Kodi is the active source.

- One `switch` per TV. On = CEC `activate` (TV on and switched to Kodi's input),
  off = CEC `standby`. Attributes expose the raw CEC reading, its age, the pending
  command and why the switch is unavailable, if it is.
- One `update` entity for the whole integration that reports new versions from
  `update-manifest.json`. It does not install: installation is manual.

## State rules

They come from measurements on real hardware (see the addon's `docs/DESIGN.md`):

| Situation | Measured | Rule |
|---|---|---|
| TV switching state | does not answer CEC: `unknown` for ~2 s after standby and **over 30 s after power-on** | keep the last known state for up to 90 s |
| Command sent | the change is published 3-23 s later | show the requested state until a reading taken **after** the command confirms it, or 60 s pass |
| Box just booted | first reading carries an unsynchronised clock (1980) | a reading older than 3 x poll interval (min 90 s) makes the switch unavailable |
| Addon not publishing / incompatible protocol | - | unavailable, with the reason as attribute |
| TV not answering for a long time (e.g. unplugged) | CEC NACK | state **unknown**, never off |
| Kodi unreachable | - | unavailable |

The rules live in `model.py`, which does not import Home Assistant and is covered
by `tests/cec_tv/test_model.py`.

## Installation

HACS supports a single integration per repository and this repository hosts
several, so installation is manual: copy `custom_components/cec_tv` into the Home
Assistant configuration directory, restart, and add **CEC TV** from
*Settings > Devices & services*, once per TV.

Requirements on each Kodi box: web server enabled (*Settings > Services > Control*)
and `script.cec.control` 0.2.0 or later installed and enabled.
