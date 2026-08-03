package setup

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/config"
	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type InstallOptions struct {
	ConfigPath  string
	Token       string
	Port        int
	Bind        string
	Allow       []string
	NoTLS       bool
	NoFirewall  bool
	NoStart     bool
	SANs        []string
	Reconfigure bool
	Quiet       bool
	Force       bool
	Explicit    map[string]bool
}

type InstallResult struct {
	Token       string
	URL         string
	Fingerprint string
	Warnings    []string
}

type preparedInstall struct {
	options         InstallOptions
	configuration   config.Config
	configPath      string
	configCandidate string
	binaryCandidate string
	binaryChanged   bool
	configChanged   bool
	serviceBefore   winapi.ServiceSnapshot
	contract        winapi.ServiceContract
	certificate     CertificateInfo
	firstInstall    bool
	firewallAdded   bool
	eventRegistered bool
}

func Install(options InstallOptions) (InstallResult, error) {
	platform := winapi.Current()
	elevated, err := platform.IsElevated()
	if err != nil {
		return InstallResult{}, fmt.Errorf("check administrator privileges: %w", err)
	}
	if !elevated {
		return InstallResult{}, fmt.Errorf("installation requires an elevated Administrator command prompt")
	}
	supported, version, err := platform.IsSupportedWindows()
	if err != nil {
		return InstallResult{}, fmt.Errorf("check Windows version: %w", err)
	}
	if !supported {
		return InstallResult{}, fmt.Errorf("Windows version %s is not supported", version)
	}
	prepared, result, err := prepareInstall(platform, options)
	if err != nil {
		return InstallResult{}, err
	}
	if err := applyInstall(platform, prepared); err != nil {
		if prepared.firstInstall {
			if prepared.firewallAdded {
				_ = removeFirewallRule(platform)
			}
			if prepared.eventRegistered {
				_ = removeEventSource(platform)
			}
		}
		return InstallResult{}, err
	}
	return result, nil
}

func prepareInstall(platform winapi.Platform, options InstallOptions) (*preparedInstall, InstallResult, error) {
	configPath, err := config.ResolvePath(options.ConfigPath, os.LookupEnv)
	if err != nil {
		return nil, InstallResult{}, err
	}
	for _, directory := range []string{
		winapi.InstallDirectory, winapi.DataDirectory,
		filepath.Join(winapi.DataDirectory, "state"), filepath.Join(winapi.DataDirectory, "certs"),
		filepath.Join(winapi.DataDirectory, "logs"), filepath.Join(winapi.DataDirectory, "update"),
	} {
		if err := os.MkdirAll(directory, 0o700); err != nil {
			return nil, InstallResult{}, fmt.Errorf("create directory %q: %w", directory, err)
		}
	}
	if err := applyDataDACL(platform); err != nil {
		return nil, InstallResult{}, fmt.Errorf("apply ProgramData DACL: %w", err)
	}
	serviceBefore, err := platform.ServiceSnapshot()
	if err != nil {
		return nil, InstallResult{}, fmt.Errorf("inspect service: %w", err)
	}
	firstInstall := !regularFile(configPath)
	warnings := make([]string, 0)
	var cfg config.Config
	var existingConfig []byte
	if firstInstall {
		cfg = config.Defaults()
	} else {
		existingConfig, err = os.ReadFile(configPath)
		if err != nil {
			return nil, InstallResult{}, fmt.Errorf("read existing config: %w", err)
		}
		cfg, warnings, err = config.Decode(existingConfig)
		if err != nil {
			return nil, InstallResult{}, fmt.Errorf("decode existing config: %w", err)
		}
	}
	applyConfigurationFlags(&cfg, options, firstInstall, &warnings)
	if firstInstall && cfg.API.Token == "" {
		cfg.API.Token, err = generateToken()
		if err != nil {
			return nil, InstallResult{}, err
		}
	}
	validation, err := config.Validate(cfg)
	if err != nil {
		return nil, InstallResult{}, fmt.Errorf("validate candidate config: %w", err)
	}
	warnings = append(warnings, validation.Warnings...)
	configChanged := firstInstall || options.Reconfigure
	configCandidate := ""
	if configChanged {
		configCandidate = configPath + ".new"
		var data []byte
		var marshalErr error
		if firstInstall {
			data, marshalErr = config.Marshal(cfg, false)
		} else {
			data, marshalErr = config.Patch(existingConfig, configurationUpdates(options))
		}
		if marshalErr != nil {
			return nil, InstallResult{}, marshalErr
		}
		if err := os.MkdirAll(filepath.Dir(configPath), 0o700); err != nil {
			return nil, InstallResult{}, fmt.Errorf("create config directory: %w", err)
		}
		if err := os.WriteFile(configCandidate, data, 0o600); err != nil {
			return nil, InstallResult{}, fmt.Errorf("write config candidate: %w", err)
		}
	}

	source, err := os.Executable()
	if err != nil {
		return nil, InstallResult{}, fmt.Errorf("resolve running executable: %w", err)
	}
	binaryChanged, err := filesDiffer(source, winapi.InstalledExecutable)
	if err != nil {
		return nil, InstallResult{}, err
	}
	binaryCandidate := ""
	if binaryChanged {
		binaryCandidate = winapi.InstalledExecutable + ".new"
		if err := copyFile(source, binaryCandidate); err != nil {
			return nil, InstallResult{}, fmt.Errorf("prepare binary candidate: %w", err)
		}
	}

	certificate := CertificateInfo{}
	if cfg.TLS.Enabled {
		certificate, _, err = EnsureCertificate(cfg.TLS.CertFile, cfg.TLS.KeyFile, cfg.TLS.SelfSigned.ValidDays, cfg.TLS.SelfSigned.SubjectAltNames, false)
		if err != nil {
			return nil, InstallResult{}, fmt.Errorf("ensure TLS certificate: %w", err)
		}
	}
	if err := registerEventSource(platform); err != nil {
		return nil, InstallResult{}, fmt.Errorf("register Event Log source: %w", err)
	}
	firewallAdded := false
	if !options.NoFirewall {
		if err := addFirewallRule(platform, cfg.API.BindPort); err != nil {
			if !serviceBefore.Exists {
				_ = removeEventSource(platform)
			}
			return nil, InstallResult{}, fmt.Errorf("create firewall rule: %w", err)
		}
		firewallAdded = true
	}
	arguments := []string{"service"}
	if !strings.EqualFold(filepath.Clean(configPath), filepath.Clean(config.WindowsDefaultConfigPath)) {
		arguments = append(arguments, "--config", configPath)
	}
	contract := winapi.ServiceContract{Executable: winapi.InstalledExecutable, Arguments: arguments}
	prepared := &preparedInstall{
		options: options, configuration: cfg, configPath: configPath, configCandidate: configCandidate,
		binaryCandidate: binaryCandidate, binaryChanged: binaryChanged, configChanged: configChanged,
		serviceBefore: serviceBefore, contract: contract, certificate: certificate,
		firstInstall: !serviceBefore.Exists, firewallAdded: firewallAdded, eventRegistered: true,
	}
	if len(cfg.API.AllowedClients) == 0 && !options.Quiet {
		warnings = append(warnings, "api.allowed_clients is empty; restrict it to the Home Assistant address when possible")
	}
	return prepared, InstallResult{
		Token: cfg.API.Token, URL: endpointURL(cfg), Fingerprint: certificate.Fingerprint, Warnings: warnings,
	}, nil
}

func applyInstall(platform winapi.Platform, prepared *preparedInstall) error {
	if prepared.serviceBefore.Exists {
		if err := platform.StopService(60 * time.Second); err != nil {
			return fmt.Errorf("stop existing service before transaction: %w", err)
		}
	}
	binaryBackup := winapi.InstalledExecutable + ".previous"
	configBackup := prepared.configPath + ".previous"
	binaryPromoted := false
	configPromoted := false
	binaryBackedUp := false
	configBackedUp := false
	serviceApplied := false
	rollback := func(cause error) error {
		if serviceApplied || prepared.serviceBefore.Exists {
			_ = platform.StopService(15 * time.Second)
		}
		if binaryBackedUp && regularFile(binaryBackup) {
			_ = replacePortable(platform, binaryBackup, winapi.InstalledExecutable)
		} else if binaryPromoted {
			_ = os.Remove(winapi.InstalledExecutable)
		}
		if configBackedUp && regularFile(configBackup) {
			_ = replacePortable(platform, configBackup, prepared.configPath)
		} else if configPromoted {
			_ = os.Remove(prepared.configPath)
		}
		if prepared.serviceBefore.Exists {
			_ = platform.ApplyService(prepared.serviceBefore.Contract)
			_ = platform.StartService()
		} else {
			_ = platform.DeleteService()
		}
		return fmt.Errorf("installation transaction failed and was rolled back: %w", cause)
	}

	if prepared.binaryChanged {
		if regularFile(winapi.InstalledExecutable) {
			_ = os.Remove(binaryBackup)
			if err := replacePortable(platform, winapi.InstalledExecutable, binaryBackup); err != nil {
				return rollback(fmt.Errorf("back up installed binary: %w", err))
			}
			binaryBackedUp = true
		}
		if err := replacePortable(platform, prepared.binaryCandidate, winapi.InstalledExecutable); err != nil {
			return rollback(fmt.Errorf("promote binary candidate: %w", err))
		}
		binaryPromoted = true
	}
	if prepared.configChanged {
		if regularFile(prepared.configPath) {
			_ = os.Remove(configBackup)
			if err := replacePortable(platform, prepared.configPath, configBackup); err != nil {
				return rollback(fmt.Errorf("back up config: %w", err))
			}
			configBackedUp = true
		}
		if err := replacePortable(platform, prepared.configCandidate, prepared.configPath); err != nil {
			return rollback(fmt.Errorf("promote config candidate: %w", err))
		}
		configPromoted = true
	}
	if err := platform.ApplyService(prepared.contract); err != nil {
		return rollback(fmt.Errorf("apply SCM contract: %w", err))
	}
	serviceApplied = true
	if !prepared.options.NoStart {
		if err := platform.StartService(); err != nil {
			return rollback(fmt.Errorf("start service: %w", err))
		}
		if err := HealthCheck(prepared.configuration, 15*time.Second); err != nil {
			return rollback(err)
		}
	}
	return nil
}

func Uninstall(purge bool) error {
	platform := winapi.Current()
	elevated, err := platform.IsElevated()
	if err != nil || !elevated {
		return fmt.Errorf("uninstall requires an elevated Administrator command prompt")
	}
	_ = platform.StopService(60 * time.Second)
	if err := platform.DeleteService(); err != nil {
		return fmt.Errorf("delete service: %w", err)
	}
	if err := removeFirewallRule(platform); err != nil {
		return fmt.Errorf("remove firewall rule: %w", err)
	}
	if err := removeEventSource(platform); err != nil {
		return fmt.Errorf("remove Event Log source: %w", err)
	}
	if err := os.RemoveAll(winapi.InstallDirectory); err != nil {
		_ = platform.RemoveFileOnReboot(winapi.InstalledExecutable)
		return fmt.Errorf("remove installation directory: %w", err)
	}
	if purge {
		if err := os.RemoveAll(winapi.DataDirectory); err != nil {
			return fmt.Errorf("purge ProgramData directory: %w", err)
		}
	}
	return nil
}

func HealthCheck(cfg config.Config, timeout time.Duration) error {
	host := cfg.API.BindHost
	if host == "0.0.0.0" {
		host = "127.0.0.1"
	} else if host == "::" {
		host = "::1"
	}
	scheme := "http"
	transport := &http.Transport{}
	if cfg.TLS.Enabled {
		scheme = "https"
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true} // The self-signed fingerprint is reported for out-of-band verification.
	}
	url := scheme + "://" + net.JoinHostPort(host, strconv.Itoa(cfg.API.BindPort)) + "/health"
	deadline := time.Now().Add(timeout)
	var lastError error
	for time.Now().Before(deadline) {
		attemptTimeout := 2 * time.Second
		if remaining := time.Until(deadline); remaining < attemptTimeout {
			attemptTimeout = remaining
		}
		ctx, cancel := context.WithTimeout(context.Background(), attemptTimeout)
		request, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		response, err := (&http.Client{Timeout: attemptTimeout, Transport: transport}).Do(request)
		if err == nil {
			var payload struct {
				Status string `json:"status"`
			}
			decodeErr := json.NewDecoder(io.LimitReader(response.Body, 4096)).Decode(&payload)
			_ = response.Body.Close()
			if response.StatusCode == http.StatusOK && decodeErr == nil && payload.Status == "ok" {
				cancel()
				return nil
			}
			lastError = fmt.Errorf("HTTP %d with an invalid health payload", response.StatusCode)
		} else {
			lastError = err
		}
		cancel()
		if time.Until(deadline) > 250*time.Millisecond {
			time.Sleep(250 * time.Millisecond)
		}
	}
	return fmt.Errorf("health-check %s failed within %s: %v", url, timeout, lastError)
}

func applyConfigurationFlags(cfg *config.Config, options InstallOptions, first bool, warnings *[]string) {
	apply := first || options.Reconfigure
	fields := []string{"token", "port", "bind", "allow", "san", "no-tls"}
	if !apply {
		for _, field := range fields {
			if options.Explicit[field] {
				*warnings = append(*warnings, "ignored --"+field+" because config already exists; use --reconfigure to apply it")
			}
		}
		return
	}
	if options.Explicit["token"] {
		cfg.API.Token = options.Token
	}
	if options.Explicit["port"] {
		cfg.API.BindPort = options.Port
	}
	if options.Explicit["bind"] {
		cfg.API.BindHost = options.Bind
	}
	if options.Explicit["allow"] {
		cfg.API.AllowedClients = append([]string(nil), options.Allow...)
	}
	if options.Explicit["san"] {
		cfg.TLS.SelfSigned.SubjectAltNames = append([]string(nil), options.SANs...)
	}
	if options.Explicit["no-tls"] {
		cfg.TLS.Enabled = !options.NoTLS
	}
}

func configurationUpdates(options InstallOptions) map[string]any {
	updates := make(map[string]any)
	if options.Explicit["token"] {
		updates["api.token"] = options.Token
	}
	if options.Explicit["port"] {
		updates["api.bind_port"] = options.Port
	}
	if options.Explicit["bind"] {
		updates["api.bind_host"] = options.Bind
	}
	if options.Explicit["allow"] {
		updates["api.allowed_clients"] = append([]string(nil), options.Allow...)
	}
	if options.Explicit["san"] {
		updates["tls.self_signed.subject_alt_names"] = append([]string(nil), options.SANs...)
	}
	if options.Explicit["no-tls"] {
		updates["tls.enabled"] = !options.NoTLS
	}
	return updates
}

func generateToken() (string, error) {
	value := make([]byte, 32)
	if _, err := rand.Read(value); err != nil {
		return "", fmt.Errorf("generate API token: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(value), nil
}

func filesDiffer(source, destination string) (bool, error) {
	if !regularFile(destination) {
		return true, nil
	}
	sourceHash, err := fileHash(source)
	if err != nil {
		return false, err
	}
	destinationHash, err := fileHash(destination)
	if err != nil {
		return false, err
	}
	return sourceHash != destinationHash, nil
}

func fileHash(path string) ([sha256.Size]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return [sha256.Size]byte{}, fmt.Errorf("open %q for hashing: %w", path, err)
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return [sha256.Size]byte{}, fmt.Errorf("hash %q: %w", path, err)
	}
	var result [sha256.Size]byte
	copy(result[:], hash.Sum(nil))
	return result, nil
}

func copyFile(source, destination string) error {
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	output, err := os.OpenFile(destination, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o755)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(output, input)
	closeErr := output.Close()
	if copyErr != nil {
		return copyErr
	}
	return closeErr
}

func endpointURL(cfg config.Config) string {
	scheme := "http"
	if cfg.TLS.Enabled {
		scheme = "https"
	}
	host := cfg.API.BindHost
	if host == "0.0.0.0" {
		host = "<host>"
	} else if host == "::" {
		host = "<host-v6>"
	}
	return scheme + "://" + net.JoinHostPort(host, strconv.Itoa(cfg.API.BindPort))
}
