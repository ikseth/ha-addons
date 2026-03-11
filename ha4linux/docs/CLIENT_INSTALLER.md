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
- Config en `/etc/ha4linux/ha4linux.env`
- TLS autofirmado en `/etc/ha4linux/certs`
- Politicas de apps en `/etc/ha4linux/policies/apps.json`
  - Se crea vacio por defecto (`{\"apps\": []}`); anade solo las apps que quieras controlar.
- Servicio `systemd` `ha4linux.service`
- Politica `sudoers` limitada para `loginctl`

## Ajustes post-instalacion

Editar configuracion:

```bash
sudo nano /etc/ha4linux/ha4linux.env
```

Variables nuevas de monitorizacion avanzada:

- `HA4LINUX_SENSORS_RAID=true|false`
- `HA4LINUX_SENSORS_VIRTUALBOX=true|false`
- `HA4LINUX_VIRTUALBOX_USER=<usuario_con_vms>`
- `HA4LINUX_SENSORS_SERVICES=true|false`
- `HA4LINUX_SERVICES_WATCHLIST=apache2.service,mariadb.service,smbd.service,docker.service`
- `HA4LINUX_SENSORS_FILESYSTEM=true|false`
- `HA4LINUX_FILESYSTEM_EXCLUDE_TYPES=tmpfs,ramfs,...,nfs,nfs4,cifs,...`
- `HA4LINUX_FILESYSTEM_EXCLUDE_MOUNTS=/proc,/sys,/dev,/run,/var/lib/docker,/var/lib/containers`
- `HA4LINUX_READONLY_MODE=true|false` (desactiva actuadores en entornos criticos)

Variables de update remoto (opcional, desactivado por defecto):

- `HA4LINUX_REMOTE_UPDATE_ENABLED=true|false`
- `HA4LINUX_REMOTE_UPDATE_MANIFEST_URL=https://.../manifest.json`
- `HA4LINUX_REMOTE_UPDATE_CHANNEL=stable`
- `HA4LINUX_REMOTE_UPDATE_CHECK_INTERVAL_SEC=1800`
- `HA4LINUX_REMOTE_UPDATE_CHECK_TIMEOUT_SEC=10`
- `HA4LINUX_REMOTE_UPDATE_COMMAND_TIMEOUT_SEC=300`
- `HA4LINUX_REMOTE_UPDATE_APPLY_COMMAND=/usr/local/bin/ha4linux-update-apply`
- `HA4LINUX_REMOTE_UPDATE_ROLLBACK_COMMAND=/usr/local/bin/ha4linux-update-rollback`
- `HA4LINUX_REMOTE_UPDATE_ALLOW_IN_READONLY=false`

Formato minimo de manifest:

```json
{
  "version": "0.4.1",
  "changelog_url": "https://github.com/ikseth/ha-addons/releases/tag/v0.4.1"
}
```

Tambien se admite formato por canales:

```json
{
  "channels": {
    "stable": {
      "version": "0.4.1",
      "changelog_url": "https://github.com/ikseth/ha-addons/releases/tag/v0.4.1"
    }
  }
}
```

Para `HA4LINUX_SENSORS_VIRTUALBOX=true` con `HA4LINUX_VIRTUALBOX_USER` distinto de `ha4linux`,
el instalador deja configurada una regla `sudoers` de solo lectura para `VBoxManage list`.

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
sudo dpkg -i ./packaging/ha4linux-client_0.2.0_$(dpkg --print-architecture).deb
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
