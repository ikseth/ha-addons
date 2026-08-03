package main

import (
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/setup"
	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

func commandConfig(arguments []string) error {
	if len(arguments) == 0 || (arguments[0] != "print" && arguments[0] != "validate") {
		return fmt.Errorf("usage: ha4win config print|validate [--config path]")
	}
	action := arguments[0]
	flags := flag.NewFlagSet("config "+action, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	path := flags.String("config", "", "configuration path")
	if err := flags.Parse(arguments[1:]); err != nil {
		return fmt.Errorf("parse config options: %w", err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("config %s does not accept positional arguments", action)
	}
	loaded, err := config.Load(*path, os.LookupEnv)
	if err != nil {
		return winapi.NewExitError(1, "%v", err)
	}
	for _, warning := range loaded.Warnings {
		fmt.Fprintln(os.Stderr, "Warning:", warning)
	}
	if action == "print" {
		data, err := config.Marshal(loaded.Config, true)
		if err != nil {
			return err
		}
		_, err = os.Stdout.Write(data)
		return err
	}
	validation, err := config.Validate(loaded.Config)
	if err != nil {
		return winapi.NewExitError(1, "%v", err)
	}
	for _, warning := range validation.Warnings {
		fmt.Fprintln(os.Stderr, "Warning:", warning)
	}
	if loaded.Config.TLS.Enabled {
		if _, _, err := setup.EnsureCertificate(
			loaded.Config.TLS.CertFile, loaded.Config.TLS.KeyFile, loaded.Config.TLS.SelfSigned.ValidDays,
			loaded.Config.TLS.SelfSigned.SubjectAltNames, false,
		); err != nil {
			return winapi.NewExitError(2, "%v", err)
		}
	}
	if restricted, err := winapi.Current().RestrictedDACL(winapi.DataDirectory); err == nil && !restricted {
		fmt.Fprintln(os.Stderr, "Warning: ProgramData DACL is inherited or grants access beyond SYSTEM and Administrators")
	}
	fmt.Println("Configuration is valid.")
	return nil
}
