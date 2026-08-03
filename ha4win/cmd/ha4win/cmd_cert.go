package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/setup"
)

func commandCert(arguments []string) error {
	if len(arguments) == 0 || (arguments[0] != "generate" && arguments[0] != "show") {
		return fmt.Errorf("usage: ha4win cert generate|show [options]")
	}
	action := arguments[0]
	flags := flag.NewFlagSet("cert "+action, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	path := flags.String("config", "", "configuration path")
	force := flags.Bool("force", false, "replace an existing certificate")
	sans := flags.String("san", "", "comma-separated additional SANs")
	if err := flags.Parse(arguments[1:]); err != nil {
		return fmt.Errorf("parse cert options: %w", err)
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("cert %s does not accept positional arguments", action)
	}
	loaded, err := config.Load(*path, os.LookupEnv)
	if err != nil {
		return err
	}
	if action == "generate" {
		info, generated, err := setup.EnsureCertificate(
			loaded.Config.TLS.CertFile, loaded.Config.TLS.KeyFile, loaded.Config.TLS.SelfSigned.ValidDays,
			append(loaded.Config.TLS.SelfSigned.SubjectAltNames, splitComma(*sans)...), *force,
		)
		if err != nil {
			return err
		}
		if generated {
			fmt.Println("TLS certificate generated.")
		} else {
			fmt.Println("TLS certificate already exists; use --force to replace it.")
		}
		printCertificate(info)
		return nil
	}
	if *force || *sans != "" {
		return fmt.Errorf("--force and --san are only valid with cert generate")
	}
	info, err := setup.ReadCertificate(loaded.Config.TLS.CertFile)
	if err != nil {
		return err
	}
	printCertificate(info)
	return nil
}

func printCertificate(info setup.CertificateInfo) {
	fmt.Println("Subject:", info.Subject)
	fmt.Println("SHA-256 fingerprint:", info.Fingerprint)
	fmt.Println("Valid from:", info.NotBefore.UTC().Format("2006-01-02T15:04:05Z"))
	fmt.Println("Valid until:", info.NotAfter.UTC().Format("2006-01-02T15:04:05Z"))
	fmt.Println("DNS SANs:", strings.Join(info.DNSNames, ", "))
	ipAddresses := make([]string, 0, len(info.IPAddresses))
	for _, address := range info.IPAddresses {
		ipAddresses = append(ipAddresses, address.String())
	}
	fmt.Println("IP SANs:", strings.Join(ipAddresses, ", "))
}
