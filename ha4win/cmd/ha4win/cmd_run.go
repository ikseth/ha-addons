package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/api"
	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/logging"
	"github.com/ikseth/ha-addons/ha4win/internal/setup"
	"github.com/ikseth/ha-addons/ha4win/internal/version"
	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type application struct {
	configPath string
	console    bool
	server     *api.Server
	logger     *logging.Logger
}

func commandRun(arguments []string) error {
	configPath, err := parseConfigFlag("run", arguments)
	if err != nil {
		return err
	}
	app := &application{configPath: configPath, console: true}
	if err := app.Start(func(uint32) {}); err != nil {
		return err
	}
	wait := make(chan error, 1)
	go func() { wait <- app.Wait() }()
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)
	select {
	case err := <-wait:
		return err
	case <-signals:
		if err := app.Stop(10 * time.Second); err != nil {
			return err
		}
		return <-wait
	}
}

func commandService(arguments []string) error {
	configPath, err := parseConfigFlag("service", arguments)
	if err != nil {
		return err
	}
	app := &application{configPath: configPath}
	err = winapi.Current().RunService(app)
	if errors.Is(err, winapi.ErrNotService) {
		return winapi.NewExitError(4, "%v", err)
	}
	return err
}

func parseConfigFlag(name string, arguments []string) (string, error) {
	flags := flag.NewFlagSet(name, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	path := flags.String("config", "", "configuration path")
	if err := flags.Parse(arguments); err != nil {
		return "", fmt.Errorf("parse %s options: %w", name, err)
	}
	if flags.NArg() != 0 {
		return "", fmt.Errorf("%s does not accept positional arguments", name)
	}
	return *path, nil
}

func (a *application) Start(report func(uint32)) error {
	report(2)
	loaded, err := config.Load(a.configPath, os.LookupEnv)
	if err != nil {
		logStartupError(a.console, "configuration load failed: "+err.Error())
		return winapi.NewExitError(1, "load configuration: %v", err)
	}
	a.configPath = loaded.Path
	logPath := filepath.Join(winapi.DataDirectory, "logs", "ha4win.log")
	a.logger, err = logging.New(logging.Options{
		Path: logPath, Level: loaded.Config.Logging.Level, FileEnabled: loaded.Config.Logging.FileEnabled,
		MaxSizeMB: loaded.Config.Logging.MaxSizeMB, MaxFiles: loaded.Config.Logging.MaxFiles,
		EventLogEnabled: loaded.Config.Logging.EventLogEnabled, Console: a.console,
	})
	if err != nil {
		return winapi.NewExitError(1, "initialize logging: %v", err)
	}
	for _, warning := range loaded.Warnings {
		a.logger.Warning(warning)
	}
	validation, err := config.Validate(loaded.Config)
	if err != nil {
		a.logger.Error("configuration validation failed: " + err.Error())
		return winapi.NewExitError(1, "configuration validation failed: %v", err)
	}
	for _, warning := range validation.Warnings {
		a.logger.Warning(warning)
	}
	report(3)
	if loaded.Config.TLS.Enabled {
		if _, _, err := setup.EnsureCertificate(
			loaded.Config.TLS.CertFile, loaded.Config.TLS.KeyFile, loaded.Config.TLS.SelfSigned.ValidDays,
			loaded.Config.TLS.SelfSigned.SubjectAltNames, false,
		); err != nil {
			a.logger.Error("TLS certificate setup failed: " + err.Error())
			return winapi.NewExitError(2, "TLS certificate setup failed: %v", err)
		}
	}
	report(4)
	a.server, err = api.New(api.Options{Config: loaded.Config, ConfigPath: loaded.Path, Logger: a.logger})
	if err != nil {
		return winapi.NewExitError(1, "initialize API server: %v", err)
	}
	if err := a.server.Start(); err != nil {
		var startError *api.StartError
		if errors.As(err, &startError) && startError.Kind == api.StartTLS {
			return winapi.NewExitError(2, "%v", err)
		}
		if errors.As(err, &startError) && startError.Kind == api.StartListen {
			return winapi.NewExitError(3, "%v", err)
		}
		return err
	}
	a.logger.Info(fmt.Sprintf("service started: version=%s", version.Version))
	return nil
}

func logStartupError(console bool, message string) {
	logger, err := logging.New(logging.Options{
		Path: filepath.Join(winapi.DataDirectory, "logs", "ha4win.log"), Level: "info",
		FileEnabled: true, MaxSizeMB: 10, MaxFiles: 5, EventLogEnabled: true, Console: console,
	})
	if err == nil {
		logger.Error(message)
		_ = logger.Close()
	}
}

func (a *application) Stop(timeout time.Duration) error {
	if a.server == nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	a.logger.Info(fmt.Sprintf("service stopping: version=%s", version.Version))
	return a.server.Shutdown(ctx)
}

func (a *application) Wait() error {
	if a.server == nil {
		return nil
	}
	err := a.server.Wait()
	if a.logger != nil {
		a.logger.Info(fmt.Sprintf("service stopped: version=%s", version.Version))
		_ = a.logger.Close()
	}
	return err
}
