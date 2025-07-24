# Home Assistant Log to Syslog

Add-on for Home Assistant OS that forwards `home-assistant.log` in real time to a remote syslog server using syslog-ng.

## Options

- `remote_host`: IP or hostname of the remote syslog server (default: 192.168.50.62)
- `remote_port`: Port (default: 514)
- `facility`: Syslog facility (default: local5)

## Usage

1. Install the add-on.
2. Configure options as needed.
3. Start the add-on.
