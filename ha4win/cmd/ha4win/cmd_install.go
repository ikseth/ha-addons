package main

import (
	"flag"
	"fmt"
	"io"
	"strings"

	"github.com/ikseth/ha-addons/ha4win/internal/setup"
)

func commandInstall(arguments []string) error {
	flags := flag.NewFlagSet("install", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	var options setup.InstallOptions
	var allow string
	var sans string
	flags.StringVar(&options.Token, "token", "", "API bearer token")
	flags.IntVar(&options.Port, "port", 8099, "listen port")
	flags.StringVar(&options.Bind, "bind", "0.0.0.0", "listen address")
	flags.StringVar(&allow, "allow", "", "comma-separated client CIDRs")
	flags.BoolVar(&options.NoTLS, "no-tls", false, "disable TLS")
	flags.BoolVar(&options.NoFirewall, "no-firewall", false, "do not create a firewall rule")
	flags.BoolVar(&options.NoStart, "no-start", false, "do not start the service")
	flags.StringVar(&options.ConfigPath, "config", "", "configuration path")
	flags.StringVar(&sans, "san", "", "comma-separated additional certificate SANs")
	flags.BoolVar(&options.Reconfigure, "reconfigure", false, "apply configuration flags to an existing config")
	flags.BoolVar(&options.Quiet, "quiet", false, "minimal output")
	flags.BoolVar(&options.Force, "force", false, "confirm unsafe options")
	if err := flags.Parse(arguments); err != nil {
		return fmt.Errorf("parse install options: %w", err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("install does not accept positional arguments")
	}
	options.Explicit = make(map[string]bool)
	flags.Visit(func(item *flag.Flag) { options.Explicit[item.Name] = true })
	options.Allow = splitComma(allow)
	options.SANs = splitComma(sans)
	if options.NoTLS && !options.Force {
		return fmt.Errorf("--no-tls requires --force because it can expose the bearer token in clear text")
	}
	result, err := setup.Install(options)
	if err != nil {
		return err
	}
	if options.Quiet {
		fmt.Println("API token:", result.Token)
		return nil
	}
	fmt.Println("HA4Win installation completed.")
	fmt.Println("URL:", result.URL)
	fmt.Println("API token:", result.Token)
	if result.Fingerprint != "" {
		fmt.Println("TLS certificate SHA-256:", result.Fingerprint)
	}
	for _, warning := range result.Warnings {
		fmt.Println("Warning:", warning)
	}
	return nil
}

func commandUninstall(arguments []string) error {
	flags := flag.NewFlagSet("uninstall", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	purge := flags.Bool("purge", false, "remove ProgramData as well")
	quiet := flags.Bool("quiet", false, "minimal output")
	if err := flags.Parse(arguments); err != nil {
		return fmt.Errorf("parse uninstall options: %w", err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("uninstall does not accept positional arguments")
	}
	if err := setup.Uninstall(*purge); err != nil {
		return err
	}
	if !*quiet {
		fmt.Println("HA4Win was uninstalled.")
	}
	return nil
}

func splitComma(value string) []string {
	if strings.TrimSpace(value) == "" {
		return []string{}
	}
	parts := strings.Split(value, ",")
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part != "" {
			result = append(result, part)
		}
	}
	return result
}
