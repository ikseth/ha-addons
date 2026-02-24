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
- Servicio `systemd` `ha4linux.service`
- Politica `sudoers` limitada para `loginctl`

## Ajustes post-instalacion

Editar configuracion:

```bash
sudo nano /etc/ha4linux/ha4linux.env
```

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
