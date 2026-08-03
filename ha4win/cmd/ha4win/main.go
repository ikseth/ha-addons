package main

import (
	"errors"
	"fmt"
	"os"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

func main() {
	os.Exit(runCommand(os.Args[1:]))
}

func runCommand(arguments []string) int {
	if len(arguments) == 0 {
		printUsage()
		return 1
	}
	var err error
	switch arguments[0] {
	case "install":
		err = commandInstall(arguments[1:])
	case "uninstall":
		err = commandUninstall(arguments[1:])
	case "service":
		err = commandService(arguments[1:])
	case "run":
		err = commandRun(arguments[1:])
	case "start", "stop", "restart", "status":
		err = commandServiceControl(arguments[0], arguments[1:])
	case "version":
		err = commandVersion(arguments[1:])
	case "config":
		err = commandConfig(arguments[1:])
	case "cert":
		err = commandCert(arguments[1:])
	case "update":
		err = commandUpdate(arguments[1:])
	case "help", "--help", "-h":
		printUsage()
		return 0
	default:
		err = fmt.Errorf("unknown subcommand %q", arguments[0])
	}
	if err == nil {
		return 0
	}
	if !errors.Is(err, errAlreadyReported) {
		fmt.Fprintln(os.Stderr, "Error:", err)
	}
	return winapi.ExitCode(err)
}

var errAlreadyReported = errors.New("error already reported")

func printUsage() {
	fmt.Fprint(os.Stderr, `Usage: ha4win <command> [options]

Commands:
  install, uninstall       Install or remove the Windows service
  service, run             Run under SCM or in the foreground
  start, stop, restart     Control the Windows service
  status                   Show SCM state and local health
  version                  Show build version
  config print|validate    Inspect effective configuration
  cert generate|show       Manage the TLS certificate
  update apply|rollback    Reserved for a later phase`)
	fmt.Fprintln(os.Stderr)
}
