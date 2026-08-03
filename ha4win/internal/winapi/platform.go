package winapi

import (
	"errors"
	"fmt"
	"time"
)

const (
	ServiceName         = "ha4win"
	ServiceDisplayName  = "HA4Win Workstation API"
	EventSource         = "HA4Win"
	FirewallRuleName    = "HA4Win Workstation API"
	InstallDirectory    = `C:\Program Files\HA4Win`
	InstalledExecutable = `C:\Program Files\HA4Win\ha4win.exe`
	DataDirectory       = `C:\ProgramData\HA4Win`
)

var (
	ErrUnsupported = errors.New("operation is only supported on Windows")
	ErrNotService  = errors.New("service command was invoked outside the Windows Service Control Manager")
)

type ExitError struct {
	Code int
	Err  error
}

func (e *ExitError) Error() string { return e.Err.Error() }
func (e *ExitError) Unwrap() error { return e.Err }

func NewExitError(code int, format string, arguments ...any) error {
	return &ExitError{Code: code, Err: fmt.Errorf(format, arguments...)}
}

func ExitCode(err error) int {
	var coded *ExitError
	if errors.As(err, &coded) {
		return coded.Code
	}
	return 1
}

type ServiceContract struct {
	Executable     string
	Arguments      []string
	BinaryPathName string
}

type ServiceSnapshot struct {
	Exists   bool
	Contract ServiceContract
}

type ServiceStatus struct {
	State string
	PID   uint32
}

type ServiceApplication interface {
	Start(reportCheckpoint func(uint32)) error
	Stop(timeout time.Duration) error
	Wait() error
}

type Platform interface {
	IsElevated() (bool, error)
	IsSupportedWindows() (bool, string, error)
	ApplyRestrictedDACL(string) error
	RestrictedDACL(string) (bool, error)
	InstallEventSource() error
	RemoveEventSource() error
	ServiceSnapshot() (ServiceSnapshot, error)
	ApplyService(ServiceContract) error
	DeleteService() error
	StartService() error
	StopService(time.Duration) error
	ServiceStatus() (ServiceStatus, error)
	RunService(ServiceApplication) error
	AddFirewallRule(int) error
	RemoveFirewallRule() error
	ReplaceFile(source, destination string) error
	RemoveFileOnReboot(string) error
	FQDN() (string, error)
}

func Current() Platform { return currentPlatform() }
