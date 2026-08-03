package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	updatepkg "github.com/ikseth/ha-addons/ha4win/internal/update"
)

func commandUpdate(arguments []string) error {
	if len(arguments) == 0 || (arguments[0] != "apply" && arguments[0] != "rollback") {
		return fmt.Errorf("usage: ha4win update apply|rollback [options]")
	}
	action := arguments[0]
	flags := flag.NewFlagSet("update "+action, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	configPath := flags.String("config", "", "configuration path")
	targetVersion := flags.String("target-version", "", "manifest version to apply")
	fromService := flags.Bool("from-service", false, "run the independent update applier")
	statePath := flags.String("state", "", "persistent update operation state")
	if err := flags.Parse(arguments[1:]); err != nil {
		return fmt.Errorf("parse update %s options: %w", action, err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("update %s does not accept positional arguments", action)
	}
	if action == "rollback" && *targetVersion != "" {
		return fmt.Errorf("--target-version is only valid for update apply")
	}
	if *fromService {
		if *statePath == "" {
			return fmt.Errorf("--state is required with --from-service")
		}
		return updatepkg.NewApplier(updatepkg.ApplierOptions{}).Run(*statePath)
	}
	if *statePath != "" {
		return fmt.Errorf("--state is only valid with --from-service")
	}
	loaded, err := config.Load(*configPath, os.LookupEnv)
	if err != nil {
		return fmt.Errorf("load configuration: %w", err)
	}
	if _, err := config.Validate(loaded.Config); err != nil {
		return fmt.Errorf("configuration validation failed: %w", err)
	}
	manager := updatepkg.NewManager(updatepkg.ManagerOptions{Config: loaded.Config, ConfigPath: loaded.Path})
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(loaded.Config.Management.RemoteUpdate.ApplyTimeoutSec)*time.Second)
	defer cancel()
	var status updatepkg.Status
	if action == "apply" {
		status = manager.Apply(ctx, *targetVersion)
	} else {
		status = manager.Rollback(ctx)
	}
	encoded, err := json.MarshalIndent(status, "", "  ")
	if err != nil {
		return err
	}
	fmt.Println(string(encoded))
	if !status.OK {
		if status.Error != nil {
			return fmt.Errorf("%s", *status.Error)
		}
		return fmt.Errorf("update %s failed", action)
	}
	return nil
}
