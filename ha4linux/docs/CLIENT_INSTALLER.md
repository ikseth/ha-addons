# Instalador cliente API (Linux)

Este proyecto incluye un instalador multi-distro para desplegar el cliente HA4Linux como servicio `systemd`.

## Soporte

- Debian
- Raspbian (Raspberry Pi OS)
- Red Hat / Rocky / Alma (dnf/yum)
- openSUSE
- Arch Linux

## Instalacion directa (recomendada para MVP)

En la maquina cliente Linux (por ejemplo `192.168.59.202`):

```bash
cd /ruta/ha-addons/ha4linux
sudo ./packaging/common/install-client.sh
```

Esto realiza:

- Instalacion de dependencias
- Creacion de usuario/grupo `ha4linux`
- Instalacion en `/opt/ha4linux`
- Config estructurada en `/etc/ha4linux/config.json`
- Bootstrap minimo en `/etc/ha4linux/ha4linux.env`
- TLS autofirmado en `/etc/ha4linux/certs`
- Politicas de apps en `/etc/ha4linux/policies/apps.json`
  - Se crea vacio por defecto (`{\"apps\": []}`); anade solo las apps que quieras controlar.
- Servicio `systemd` `ha4linux.service`
- Drop-in gestionado en `/etc/systemd/system/ha4linux.service.d/10-ha4linux-managed.conf`
- Politica `sudoers` limitada para `loginctl`, `systemctl/kill`, updates y `VBoxManage`

## Ajustes post-instalacion

Editar configuracion principal:

```bash
sudo nano /etc/ha4linux/config.json
```

Bloques relevantes del JSON:

- `modules.raid.enabled`
- `modules.virtualbox.enabled`
- `modules.virtualbox.user`
- `actuators.virtualbox.enabled`
- `actuators.virtualbox.allowed_actions`
- `actuators.virtualbox.allowed_vms`
- `actuators.virtualbox.start_type`
- `actuators.virtualbox.switch_turn_off_action`
- `modules.virtualbox.status_cache_ttl_sec`
- `modules.virtualbox.status_stale_ttl_sec`
- `modules.virtualbox.failure_backoff_min_sec`
- `modules.virtualbox.failure_backoff_max_sec`
- `modules.services.enabled`
- `modules.services.watchlist`
- `modules.network.include_interfaces`
- `modules.network.exclude_interfaces`
- `modules.network.aggregate_mode`
- `modules.filesystem.enabled`
- `modules.filesystem.exclude_types`
- `modules.filesystem.exclude_mounts`
- `modules.system_info.enabled`
- `modules.system_info.updates_enabled`
- `modules.system_info.updates_check_interval_sec`
- `modules.system_info.updates_command_timeout_sec`
- `modules.system_info.updates_max_packages`
- `readonly_mode`

Ejemplo:

```json
{
  "api": {
    "bind_port": 8099,
    "token": "CAMBIAR_TOKEN"
  },
  "modules": {
    "network": {
      "enabled": true,
      "include_interfaces": ["enp1s0", "bond0"],
      "exclude_interfaces": ["docker*", "veth*"],
      "aggregate_mode": "selected"
    },
    "raid": {
      "enabled": true
    },
    "virtualbox": {
      "enabled": true,
      "user": "ignacio",
      "status_cache_ttl_sec": 30,
      "status_stale_ttl_sec": 900,
      "failure_backoff_min_sec": 30,
      "failure_backoff_max_sec": 300
    },
    "services": {
      "enabled": true,
      "watchlist": ["apache2.service", "mariadb.service", "docker.service"]
    }
  },
  "actuators": {
    "virtualbox": {
      "enabled": true,
      "allowed_actions": ["start", "acpi_shutdown", "savestate"],
      "allowed_vms": ["vm-lab", "12345678-1234-1234-1234-123456789abc"],
      "start_type": "headless",
      "switch_turn_off_action": "acpi_shutdown"
    }
  },
  "readonly_mode": false
}
```

Fallback legacy por entorno:

- `HA4LINUX_CONFIG_FILE=/etc/ha4linux/config.json`
- Cualquier `HA4LINUX_*` antigua sigue funcionando como fallback si el valor no esta en JSON

Variables de update remoto (opcional, desactivado por defecto):

- `HA4LINUX_REMOTE_UPDATE_ENABLED=true|false`
- `HA4LINUX_REMOTE_UPDATE_MANIFEST_URL=https://.../manifest.json`
- `HA4LINUX_REMOTE_UPDATE_CHANNEL=stable`
- `HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC=1800`
- `HA4LINUX_REMOTE_UPDATE_CHECK_TIMEOUT_SEC=10`
- `HA4LINUX_REMOTE_UPDATE_COMMAND_TIMEOUT_SEC=300`
- `HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND=/opt/ha4linux/update/ha4linux-update-apply`
- `HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND=/opt/ha4linux/update/ha4linux-update-rollback`
- `HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY=false`

Variables de updates del sistema:

- `HA4LINUX_SENSORS_SYSTEM_INFO=true|false`
- `HA4LINUX_SYSTEM_UPDATES_ENABLED=true|false`
- `HA4LINUX_SYSTEM_UPDATES_CHECK_INTERVAL_SEC=86400`
- `HA4LINUX_SYSTEM_UPDATES_COMMAND_TIMEOUT_SEC=60`
- `HA4LINUX_SYSTEM_UPDATES_MAX_PACKAGES=25`

Notas operativas:

- El check de paquetes pendientes se ejecuta en segundo plano y se cachea; no bloquea `GET /v1/sensors`.
- Hasta completar el primer refresh valido, el host devolvera `updates_state=checking`.
- El modulo `virtualbox` cachea el inventario de VMs, aplica backoff exponencial y sirve cache estale controlada cuando `VBoxManage` falla, para no degradar Home Assistant.

Formato minimo de manifest para update remoto con instalacion:

```json
{
  "version": "0.5.8",
  "changelog_url": "https://github.com/ikseth/ha-addons/releases/tag/ha4linux-api-v0.5.8",
  "asset_url": "https://raw.githubusercontent.com/ikseth/ha-addons/main/ha4linux/update-assets/ha4linux-client-update-0.5.8.tar.gz",
  "sha256": "..."
}
```

Tambien se admite formato por canales:

```json
{
  "channels": {
    "stable": {
      "version": "0.5.8",
      "changelog_url": "https://github.com/ikseth/ha-addons/releases/tag/ha4linux-api-v0.5.8",
      "asset_url": "https://raw.githubusercontent.com/ikseth/ha-addons/main/ha4linux/update-assets/ha4linux-client-update-0.5.8.tar.gz",
      "sha256": "..."
    }
  }
}
```

El instalador cliente deja preparados por defecto los helpers:

- `/opt/ha4linux/update/ha4linux-update-apply`
- `/opt/ha4linux/update/ha4linux-update-rollback`
- `/opt/ha4linux/update/ha4linux-update-apply-root.py`
- `/opt/ha4linux/update/ha4linux-update-rollback-root.py`
- `/opt/ha4linux/update/ha4linux-update-apply-worker.py`
- `/opt/ha4linux/update/ha4linux-update-rollback-worker.py`

Flujo esperado:

- HA detecta una version nueva via `/v1/update/status`
- HA invoca `/v1/update/apply`
- El helper root lanza un worker transitorio con `systemd-run`, fuera del sandbox de `ha4linux.service`
- El host descarga el artefacto desde GitHub, valida `sha256`, crea backup y reinstala
- `ha4linux.service` se reinicia de forma controlada
- Si la instalacion falla, se restaura el backup automaticamente

Preflight de update remoto:

- Antes de exponer `supports_apply=true`, la API valida prerequisitos operativos.
- Si el host esta arrancado sobre un snapshot Btrfs, si `/` no es escribible o si no existe `systemd-run`, la API bloquea el `apply` y expone el motivo.
- La actualizacion ya no reescribe de forma ciega `ha4linux.service`; el unit base se preserva y la evolucion del servicio se gestiona mediante el drop-in administrado.

Para `modules.virtualbox.enabled=true` con `modules.virtualbox.user` distinto de `ha4linux`,
el instalador deja configurada una regla `sudoers` para `VBoxManage` limitada a:

- `list`
- `showvminfo --machinereadable`
- `startvm --type`
- `controlvm acpipowerbutton`
- `controlvm savestate`
- `controlvm poweroff`
- `controlvm reset`

Reiniciar servicio:

```bash
sudo systemctl restart ha4linux.service
sudo systemctl status ha4linux.service
```

## Desinstalacion

```bash
sudo ./packaging/common/uninstall-client.sh
```

## Paquetes nativos

### Debian / Raspbian (.deb)

Requisitos de build: `dpkg-deb`, `jq`.

```bash
cd /ruta/ha-addons/ha4linux
./packaging/scripts/build-deb.sh
sudo dpkg -i ./packaging/ha4linux-client_0.5.8_$(dpkg --print-architecture).deb
```

### Red Hat / openSUSE (.rpm)

Requisitos de build: `rpmbuild`, `jq`.

```bash
cd /ruta/ha-addons/ha4linux
./packaging/scripts/build-rpm.sh
sudo rpm -Uvh ./packaging/ha4linux-client-*.rpm
```

### Arch Linux (.pkg.tar.*)

Requisitos de build: `makepkg`.

```bash
cd /ruta/ha-addons/ha4linux
./packaging/scripts/build-arch.sh
sudo pacman -U ./packaging/ha4linux-client-*.pkg.tar.*
```

## Flags utiles del instalador

- `--skip-deps`: no instala dependencias (pensado para postinst de paquetes).
- `--no-start`: instala archivos pero no arranca servicio.

Ejemplo:

```bash
sudo ./packaging/common/install-client.sh --skip-deps --no-start
```
