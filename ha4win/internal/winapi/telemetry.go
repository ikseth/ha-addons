package winapi

import "time"

type CPUTimes struct {
	Idle   uint64
	Kernel uint64
	User   uint64
}

type CPUPerformance struct {
	Processes uint32
	Threads   uint32
	Handles   uint32
}

type MemoryStatus struct {
	TotalPhysical     uint64
	AvailablePhysical uint64
	CommitTotal       uint64
	CommitLimit       uint64
}

type NetworkInterface struct {
	Alias       string
	Description string
	MAC         string
	OperStatus  string
	SpeedMbps   uint64
	Type        string
	RXBytes     uint64
	TXBytes     uint64
	Hardware    bool
	Loopback    bool
	Tunnel      bool
}

type LogicalDrive struct {
	Root string
	Type string
}

type VolumeInformation struct {
	Label      string
	FileSystem string
	ReadOnly   bool
	TotalBytes uint64
	FreeBytes  uint64
}

type WatchedService struct {
	Name        string
	DisplayName string
	Exists      bool
	Status      string
	StartType   string
	PID         uint32
	CanStop     bool
	ExitCode    uint32
}

type WindowsInformation struct {
	Hostname       string
	ProductName    string
	EditionID      string
	DisplayVersion string
	CurrentBuild   string
	Major          uint32
	Minor          uint32
	BuildNumber    uint32
	UBR            uint32
	InstallDate    time.Time
	Uptime         time.Duration
	Domain         string
	DomainJoined   bool
}

func GetSystemTimes() (CPUTimes, error)                  { return getSystemTimes() }
func GetProcessorPerformance() ([]CPUTimes, error)       { return getProcessorPerformance() }
func GetSystemPerformance() (CPUPerformance, error)      { return getSystemPerformance() }
func GetMemoryStatus() (MemoryStatus, error)             { return getMemoryStatus() }
func GetNetworkInterfaces() ([]NetworkInterface, error)  { return getNetworkInterfaces() }
func GetLogicalDrives() ([]LogicalDrive, error)          { return getLogicalDrives() }
func GetVolume(root string) (VolumeInformation, error)   { return getVolume(root) }
func QueryService(name string) (WatchedService, error)   { return queryService(name) }
func GetWindowsInformation() (WindowsInformation, error) { return getWindowsInformation() }
