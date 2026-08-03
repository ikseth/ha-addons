package winapi

import "time"

type RegistryReader interface {
	KeyExists(path string) (bool, error)
	String(path, name string) (string, error)
	Strings(path, name string) ([]string, error)
	DWORD(path, name string) (uint32, error)
}

type PowerStatus struct {
	ACLineStatus       byte
	BatteryFlag        byte
	BatteryLifePercent byte
}

func NewRegistryReader() RegistryReader       { return newRegistryReader() }
func GetPowerStatus() (PowerStatus, error)    { return getPowerStatus() }
func GetUptime() (time.Duration, error)       { return getUptime() }
func ShutdownPending() (bool, *string, error) { return shutdownPending() }
