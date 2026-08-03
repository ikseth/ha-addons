package security

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
	wincom "github.com/ikseth/ha-addons/ha4win/internal/winapi/com"
)

const (
	domainFirewallKey  = `SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\DomainProfile`
	privateFirewallKey = `SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\StandardProfile`
	publicFirewallKey  = `SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\PublicProfile`
	uacKey             = `SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System`
)

type Options struct {
	Defender        bool
	Firewall        bool
	BitLocker       bool
	RefreshInterval time.Duration
	Timeout         time.Duration
	WMI             wmiProvider
}

type Source interface{ Registry() winapi.RegistryReader }
type systemSource struct{}

func (systemSource) Registry() winapi.RegistryReader { return winapi.NewRegistryReader() }

type wmiProvider interface {
	Defender(context.Context) (wincom.DefenderStatus, error)
	BitLocker(context.Context) ([]wincom.BitLockerVolume, error)
}

type comWMIProvider struct{}

func (comWMIProvider) Defender(ctx context.Context) (wincom.DefenderStatus, error) {
	return wincom.QueryDefender(ctx)
}
func (comWMIProvider) BitLocker(ctx context.Context) ([]wincom.BitLockerVolume, error) {
	return wincom.QueryBitLocker(ctx)
}

type subSnapshot[T any] struct {
	available bool
	reason    string
	value     T
}

type backgroundValue[T any] struct {
	mu       sync.RWMutex
	snapshot subSnapshot[T]
}

func (value *backgroundValue[T]) get() subSnapshot[T] {
	value.mu.RLock()
	defer value.mu.RUnlock()
	return value.snapshot
}
func (value *backgroundValue[T]) set(snapshot subSnapshot[T]) {
	value.mu.Lock()
	value.snapshot = snapshot
	value.mu.Unlock()
}

type Sensor struct {
	source           Source
	options          Options
	defender         backgroundValue[wincom.DefenderStatus]
	bitlocker        backgroundValue[[]wincom.BitLockerVolume]
	defenderPending  <-chan defenderResult
	bitLockerPending <-chan bitLockerResult
}

type defenderResult struct {
	value wincom.DefenderStatus
	err   error
}
type bitLockerResult struct {
	value []wincom.BitLockerVolume
	err   error
}

func New(options Options, source Source) *Sensor {
	if source == nil {
		source = systemSource{}
	}
	if options.RefreshInterval <= 0 {
		options.RefreshInterval = 5 * time.Minute
	}
	if options.Timeout <= 0 {
		options.Timeout = 30 * time.Second
	}
	if options.WMI == nil {
		options.WMI = comWMIProvider{}
	}
	sensor := &Sensor{source: source, options: options}
	sensor.defender.snapshot = disabledOrChecking[wincom.DefenderStatus](options.Defender)
	sensor.bitlocker.snapshot = disabledOrChecking[[]wincom.BitLockerVolume](options.BitLocker)
	if options.Defender {
		go sensor.runDefender()
	}
	if options.BitLocker {
		go sensor.runBitLocker()
	}
	return sensor
}

func disabledOrChecking[T any](enabled bool) subSnapshot[T] {
	if !enabled {
		return subSnapshot[T]{reason: "module disabled by configuration"}
	}
	return subSnapshot[T]{reason: "initial refresh in progress"}
}

func (*Sensor) ID() string { return "security" }

func (sensor *Sensor) runDefender() {
	sensor.refreshDefender()
	ticker := time.NewTicker(sensor.options.RefreshInterval)
	defer ticker.Stop()
	for range ticker.C {
		sensor.refreshDefender()
	}
}

func (sensor *Sensor) refreshDefender() {
	ctx, cancel := context.WithTimeout(context.Background(), sensor.options.Timeout)
	defer cancel()
	if sensor.defenderPending == nil {
		done := make(chan defenderResult, 1)
		sensor.defenderPending = done
		go func() { value, err := sensor.options.WMI.Defender(ctx); done <- defenderResult{value, err} }()
	}
	select {
	case result := <-sensor.defenderPending:
		sensor.defenderPending = nil
		if result.err != nil {
			sensor.defender.set(subSnapshot[wincom.DefenderStatus]{reason: result.err.Error()})
			return
		}
		sensor.defender.set(subSnapshot[wincom.DefenderStatus]{available: true, value: result.value})
	case <-ctx.Done():
		sensor.defender.set(subSnapshot[wincom.DefenderStatus]{reason: fmt.Sprintf("Defender WMI query timed out after %s", sensor.options.Timeout)})
	}
}

func (sensor *Sensor) runBitLocker() {
	sensor.refreshBitLocker()
	ticker := time.NewTicker(sensor.options.RefreshInterval)
	defer ticker.Stop()
	for range ticker.C {
		sensor.refreshBitLocker()
	}
}

func (sensor *Sensor) refreshBitLocker() {
	ctx, cancel := context.WithTimeout(context.Background(), sensor.options.Timeout)
	defer cancel()
	if sensor.bitLockerPending == nil {
		done := make(chan bitLockerResult, 1)
		sensor.bitLockerPending = done
		go func() { value, err := sensor.options.WMI.BitLocker(ctx); done <- bitLockerResult{value, err} }()
	}
	select {
	case result := <-sensor.bitLockerPending:
		sensor.bitLockerPending = nil
		if result.err != nil {
			sensor.bitlocker.set(subSnapshot[[]wincom.BitLockerVolume]{reason: result.err.Error()})
			return
		}
		copied := append([]wincom.BitLockerVolume(nil), result.value...)
		sensor.bitlocker.set(subSnapshot[[]wincom.BitLockerVolume]{available: true, value: copied})
	case <-ctx.Done():
		sensor.bitlocker.set(subSnapshot[[]wincom.BitLockerVolume]{reason: fmt.Sprintf("BitLocker WMI query timed out after %s", sensor.options.Timeout)})
	}
}

func (sensor *Sensor) Collect(ctx context.Context) (map[string]any, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	registry := sensor.source.Registry()
	firewall := firewallPayload{Available: false, Reason: "module disabled by configuration"}
	if sensor.options.Firewall {
		firewall = readFirewall(registry)
	}
	uac, err := registry.DWORD(uacKey, "EnableLUA")
	if err != nil {
		return nil, fmt.Errorf("read UAC state: %w", err)
	}
	defender := defenderData(sensor.defender.get())
	bitlocker := bitLockerData(sensor.bitlocker.get())
	issues := countIssues(defender, firewall, bitlocker, uac != 0)
	return map[string]any{
		"defender":     defender,
		"firewall":     firewall,
		"bitlocker":    bitlocker,
		"uac_enabled":  uac != 0,
		"issues_count": issues,
	}, nil
}

type defenderPayload struct {
	Available                 bool   `json:"available"`
	Reason                    string `json:"reason,omitempty"`
	AntivirusEnabled          bool   `json:"antivirus_enabled,omitempty"`
	RealtimeProtectionEnabled bool   `json:"realtime_protection_enabled,omitempty"`
	SignatureAgeDays          uint32 `json:"signature_age_days,omitempty"`
	SignatureVersion          string `json:"signature_version,omitempty"`
	LastQuickScan             string `json:"last_quick_scan,omitempty"`
}

func (payload defenderPayload) MarshalJSON() ([]byte, error) {
	if !payload.Available {
		return json.Marshal(struct {
			Available bool   `json:"available"`
			Reason    string `json:"reason"`
		}{payload.Available, payload.Reason})
	}
	return json.Marshal(struct {
		Available                 bool   `json:"available"`
		AntivirusEnabled          bool   `json:"antivirus_enabled"`
		RealtimeProtectionEnabled bool   `json:"realtime_protection_enabled"`
		SignatureAgeDays          uint32 `json:"signature_age_days"`
		SignatureVersion          string `json:"signature_version"`
		LastQuickScan             string `json:"last_quick_scan"`
	}{payload.Available, payload.AntivirusEnabled, payload.RealtimeProtectionEnabled, payload.SignatureAgeDays, payload.SignatureVersion, payload.LastQuickScan})
}

func defenderData(snapshot subSnapshot[wincom.DefenderStatus]) defenderPayload {
	if !snapshot.available {
		return defenderPayload{Reason: snapshot.reason}
	}
	return defenderPayload{
		Available: true, AntivirusEnabled: snapshot.value.AntivirusEnabled,
		RealtimeProtectionEnabled: snapshot.value.RealtimeProtectionEnabled,
		SignatureAgeDays:          snapshot.value.SignatureAgeDays, SignatureVersion: snapshot.value.SignatureVersion,
		LastQuickScan: parseWMIDate(snapshot.value.LastQuickScan),
	}
}

type firewallPayload struct {
	Available      bool   `json:"available"`
	Reason         string `json:"reason,omitempty"`
	DomainEnabled  bool   `json:"domain_enabled,omitempty"`
	PrivateEnabled bool   `json:"private_enabled,omitempty"`
	PublicEnabled  bool   `json:"public_enabled,omitempty"`
}

func (payload firewallPayload) MarshalJSON() ([]byte, error) {
	if !payload.Available {
		return json.Marshal(struct {
			Available bool   `json:"available"`
			Reason    string `json:"reason"`
		}{payload.Available, payload.Reason})
	}
	return json.Marshal(struct {
		Available      bool `json:"available"`
		DomainEnabled  bool `json:"domain_enabled"`
		PrivateEnabled bool `json:"private_enabled"`
		PublicEnabled  bool `json:"public_enabled"`
	}{payload.Available, payload.DomainEnabled, payload.PrivateEnabled, payload.PublicEnabled})
}

func readFirewall(reader winapi.RegistryReader) firewallPayload {
	values := make([]bool, 0, 3)
	for _, path := range []string{domainFirewallKey, privateFirewallKey, publicFirewallKey} {
		value, err := reader.DWORD(path, "EnableFirewall")
		if err != nil {
			return firewallPayload{Reason: err.Error()}
		}
		values = append(values, value != 0)
	}
	return firewallPayload{Available: true, DomainEnabled: values[0], PrivateEnabled: values[1], PublicEnabled: values[2]}
}

type bitLockerVolumePayload struct {
	DriveLetter      string `json:"drive_letter"`
	Protected        bool   `json:"protected"`
	ProtectionStatus string `json:"protection_status"`
	ConversionStatus string `json:"conversion_status"`
	EncryptionMethod string `json:"encryption_method"`
}

type bitLockerPayload struct {
	Available bool                     `json:"available"`
	Reason    string                   `json:"reason,omitempty"`
	Volumes   []bitLockerVolumePayload `json:"volumes"`
}

func bitLockerData(snapshot subSnapshot[[]wincom.BitLockerVolume]) bitLockerPayload {
	result := bitLockerPayload{Available: snapshot.available, Volumes: []bitLockerVolumePayload{}}
	if !snapshot.available {
		result.Reason = snapshot.reason
		return result
	}
	for _, volume := range snapshot.value {
		result.Volumes = append(result.Volumes, bitLockerVolumePayload{
			DriveLetter: volume.DriveLetter, Protected: volume.ProtectionStatus == 1,
			ProtectionStatus: protectionStatus(volume.ProtectionStatus),
			ConversionStatus: conversionStatus(volume.ConversionStatus),
			EncryptionMethod: encryptionMethod(volume.EncryptionMethod),
		})
	}
	return result
}

func countIssues(defender defenderPayload, firewall firewallPayload, bitlocker bitLockerPayload, uac bool) int {
	issues := 0
	if defender.Available {
		if !defender.AntivirusEnabled {
			issues++
		}
		if !defender.RealtimeProtectionEnabled {
			issues++
		}
	}
	if firewall.Available {
		if !firewall.DomainEnabled {
			issues++
		}
		if !firewall.PrivateEnabled {
			issues++
		}
		if !firewall.PublicEnabled {
			issues++
		}
	}
	if bitlocker.Available {
		for _, volume := range bitlocker.Volumes {
			if !volume.Protected {
				issues++
			}
		}
	}
	if !uac {
		issues++
	}
	return issues
}

func parseWMIDate(value string) string {
	value = strings.TrimSpace(value)
	if len(value) < 21 || strings.Contains(value[:14], "*") {
		return ""
	}
	base, err := time.Parse("20060102150405", value[:14])
	if err != nil {
		return ""
	}
	offset := 0
	if len(value) >= 25 && (value[21] == '+' || value[21] == '-') {
		minutes, parseErr := strconv.Atoi(value[22:25])
		if parseErr == nil {
			offset = minutes * 60
			if value[21] == '-' {
				offset = -offset
			}
		}
	}
	return time.Date(base.Year(), base.Month(), base.Day(), base.Hour(), base.Minute(), base.Second(), 0, time.FixedZone("WMI", offset)).UTC().Format(time.RFC3339)
}

func protectionStatus(value uint32) string {
	if value == 0 {
		return "off"
	}
	if value == 1 {
		return "on"
	}
	return "unknown"
}
func conversionStatus(value uint32) string {
	values := []string{"fully_decrypted", "fully_encrypted", "encryption_in_progress", "decryption_in_progress", "encryption_paused", "decryption_paused"}
	if int(value) < len(values) {
		return values[value]
	}
	return "unknown"
}
func encryptionMethod(value uint32) string {
	values := map[uint32]string{0: "none", 1: "aes_128_diffuser", 2: "aes_256_diffuser", 3: "aes_128", 4: "aes_256", 5: "hardware", 6: "xts_aes_128", 7: "xts_aes_256"}
	if result, ok := values[value]; ok {
		return result
	}
	return "unknown"
}
