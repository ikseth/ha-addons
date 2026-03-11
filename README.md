# HA Addons and Integrations

Repository with Home Assistant related components, including:

- Custom integration: `custom_components/ha4linux`
- Add-on and Linux client API: `ha4linux/`

## HACS Setup (Integration)

This repository is compatible with HACS as a custom integration repository.

1. Install HACS in Home Assistant (one-time bootstrap).
2. In Home Assistant UI, open HACS.
3. Go to `HACS > Integrations > 3 dots menu > Custom repositories`.
4. Add this repository URL as category `Integration`.
5. Search for `HA4Linux` in HACS and install.
6. Restart Home Assistant.
7. Add integration from `Settings > Devices & services > Add integration`.

## Notes

- HACS tracks updates from GitHub releases/tags.
- Integration version is declared in `custom_components/ha4linux/manifest.json`.
