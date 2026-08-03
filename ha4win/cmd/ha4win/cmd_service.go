package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/setup"
	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

func commandServiceControl(command string, arguments []string) error {
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	configPath := flags.String("config", "", "configuration path used for local health")
	if err := flags.Parse(arguments); err != nil {
		return fmt.Errorf("parse %s options: %w", command, err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("%s does not accept positional arguments", command)
	}
	platform := winapi.Current()
	switch command {
	case "start":
		return platform.StartService()
	case "stop":
		return platform.StopService(60 * time.Second)
	case "restart":
		if err := platform.StopService(60 * time.Second); err != nil {
			return err
		}
		return platform.StartService()
	case "status":
		status, err := platform.ServiceStatus()
		if err != nil {
			return err
		}
		fmt.Printf("Service state: %s\n", status.State)
		if status.PID != 0 {
			fmt.Printf("Process ID: %d\n", status.PID)
		}
		loaded, err := config.Load(*configPath, os.LookupEnv)
		if err != nil {
			return fmt.Errorf("load configuration for health probe: %w", err)
		}
		if err := setup.HealthCheck(loaded.Config, 5*time.Second); err != nil {
			fmt.Println("Local health: unavailable")
			return err
		}
		fmt.Println("Local health: ok")
		return nil
	default:
		return fmt.Errorf("unsupported service control %q", command)
	}
}
