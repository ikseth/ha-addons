//go:build windows

package winapi

import (
	"errors"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/eventlog"
	"golang.org/x/sys/windows/svc/mgr"
)

const (
	seFileObject                  = 1
	daclSecurityInformation       = 0x00000004
	protectedDACLInformation      = 0x80000000
	seDACLProtected               = 0x1000
	moveFileReplaceExisting       = 0x1
	moveFileDelayUntilReboot      = 0x4
	moveFileWriteThrough          = 0x8
	computerNameDNSFullyQualified = 3
)

var (
	advapi32 = windows.NewLazySystemDLL("advapi32.dll")
	kernel32 = windows.NewLazySystemDLL("kernel32.dll")
	ntdll    = windows.NewLazySystemDLL("ntdll.dll")

	procConvertStringSecurityDescriptor = advapi32.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW")
	procConvertSecurityDescriptorString = advapi32.NewProc("ConvertSecurityDescriptorToStringSecurityDescriptorW")
	procGetSecurityDescriptorDACL       = advapi32.NewProc("GetSecurityDescriptorDacl")
	procGetNamedSecurityInfo            = advapi32.NewProc("GetNamedSecurityInfoW")
	procSetNamedSecurityInfo            = advapi32.NewProc("SetNamedSecurityInfoW")
	procGetSecurityDescriptorControl    = advapi32.NewProc("GetSecurityDescriptorControl")
	procMoveFileEx                      = kernel32.NewProc("MoveFileExW")
	procGetComputerNameEx               = kernel32.NewProc("GetComputerNameExW")
	procRtlGetVersion                   = ntdll.NewProc("RtlGetVersion")
)

type windowsPlatform struct{}

func currentPlatform() Platform { return windowsPlatform{} }

func (windowsPlatform) IsElevated() (bool, error) {
	token := windows.GetCurrentProcessToken()
	return token.IsElevated(), nil
}

type osVersionInfo struct {
	Size        uint32
	Major       uint32
	Minor       uint32
	Build       uint32
	PlatformID  uint32
	ServicePack [128]uint16
}

func (windowsPlatform) IsSupportedWindows() (bool, string, error) {
	info := osVersionInfo{Size: uint32(unsafe.Sizeof(osVersionInfo{}))}
	status, _, _ := procRtlGetVersion.Call(uintptr(unsafe.Pointer(&info)))
	if status != 0 {
		return false, "", fmt.Errorf("RtlGetVersion failed with NTSTATUS 0x%x", status)
	}
	version := fmt.Sprintf("%d.%d.%d", info.Major, info.Minor, info.Build)
	supported := info.Major > 6 || (info.Major == 6 && info.Minor >= 1)
	return supported, version, nil
}

func (windowsPlatform) ApplyRestrictedDACL(path string) error {
	sddl, err := windows.UTF16PtrFromString("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)")
	if err != nil {
		return err
	}
	var descriptor uintptr
	result, _, callErr := procConvertStringSecurityDescriptor.Call(
		uintptr(unsafe.Pointer(sddl)), 1, uintptr(unsafe.Pointer(&descriptor)), 0,
	)
	if result == 0 {
		return fmt.Errorf("convert restricted DACL: %w", callErr)
	}
	defer windows.LocalFree(windows.Handle(descriptor))
	var present uint32
	var defaulted uint32
	var dacl uintptr
	result, _, callErr = procGetSecurityDescriptorDACL.Call(
		descriptor, uintptr(unsafe.Pointer(&present)), uintptr(unsafe.Pointer(&dacl)), uintptr(unsafe.Pointer(&defaulted)),
	)
	if result == 0 || present == 0 {
		return fmt.Errorf("read restricted DACL: %w", callErr)
	}
	pathPtr, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	result, _, _ = procSetNamedSecurityInfo.Call(
		uintptr(unsafe.Pointer(pathPtr)), seFileObject, daclSecurityInformation|protectedDACLInformation,
		0, 0, dacl, 0,
	)
	if result != 0 {
		return fmt.Errorf("SetNamedSecurityInfoW failed with error %d", result)
	}
	return nil
}

func (windowsPlatform) RestrictedDACL(path string) (bool, error) {
	pathPtr, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return false, err
	}
	var descriptor uintptr
	result, _, _ := procGetNamedSecurityInfo.Call(
		uintptr(unsafe.Pointer(pathPtr)), seFileObject, daclSecurityInformation,
		0, 0, 0, 0, uintptr(unsafe.Pointer(&descriptor)),
	)
	if result != 0 {
		return false, fmt.Errorf("GetNamedSecurityInfoW failed with error %d", result)
	}
	defer windows.LocalFree(windows.Handle(descriptor))
	var control uint16
	var revision uint32
	result, _, callErr := procGetSecurityDescriptorControl.Call(
		descriptor, uintptr(unsafe.Pointer(&control)), uintptr(unsafe.Pointer(&revision)),
	)
	if result == 0 {
		return false, fmt.Errorf("GetSecurityDescriptorControl failed: %w", callErr)
	}
	if control&seDACLProtected == 0 {
		return false, nil
	}
	var text *uint16
	var length uint32
	result, _, callErr = procConvertSecurityDescriptorString.Call(
		descriptor, 1, daclSecurityInformation, uintptr(unsafe.Pointer(&text)), uintptr(unsafe.Pointer(&length)),
	)
	if result == 0 {
		return false, fmt.Errorf("convert DACL to SDDL: %w", callErr)
	}
	defer windows.LocalFree(windows.Handle(uintptr(unsafe.Pointer(text))))
	sddl := windows.UTF16PtrToString(text)
	return strings.Contains(sddl, "(A;OICI;FA;;;SY)") && strings.Contains(sddl, "(A;OICI;FA;;;BA)") && strings.Count(sddl, "(A;") == 2, nil
}

func (windowsPlatform) InstallEventSource() error {
	return eventlog.InstallAsEventCreate(EventSource, eventlog.Info|eventlog.Warning|eventlog.Error)
}

func (windowsPlatform) RemoveEventSource() error {
	err := eventlog.Remove(EventSource)
	if errors.Is(err, windows.ERROR_FILE_NOT_FOUND) {
		return nil
	}
	return err
}

func connectService() (*mgr.Mgr, *mgr.Service, error) {
	manager, err := mgr.Connect()
	if err != nil {
		return nil, nil, err
	}
	service, err := manager.OpenService(ServiceName)
	if err != nil {
		manager.Disconnect()
		return nil, nil, err
	}
	return manager, service, nil
}

func (windowsPlatform) ServiceSnapshot() (ServiceSnapshot, error) {
	manager, err := mgr.Connect()
	if err != nil {
		return ServiceSnapshot{}, err
	}
	defer manager.Disconnect()
	service, err := manager.OpenService(ServiceName)
	if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
		return ServiceSnapshot{}, nil
	}
	if err != nil {
		return ServiceSnapshot{}, err
	}
	defer service.Close()
	cfg, err := service.Config()
	if err != nil {
		return ServiceSnapshot{}, err
	}
	return ServiceSnapshot{Exists: true, Contract: ServiceContract{BinaryPathName: cfg.BinaryPathName}}, nil
}

func serviceConfig(contract ServiceContract) mgr.Config {
	return mgr.Config{
		ServiceType:      windows.SERVICE_WIN32_OWN_PROCESS,
		StartType:        mgr.StartAutomatic,
		ErrorControl:     mgr.ErrorNormal,
		BinaryPathName:   commandLine(contract),
		ServiceStartName: "LocalSystem",
		DisplayName:      ServiceDisplayName,
		Description:      "Exposes Windows workstation telemetry to Home Assistant.",
	}
}

func commandLine(contract ServiceContract) string {
	if contract.BinaryPathName != "" {
		return contract.BinaryPathName
	}
	parts := []string{windows.EscapeArg(contract.Executable)}
	for _, argument := range contract.Arguments {
		parts = append(parts, windows.EscapeArg(argument))
	}
	return strings.Join(parts, " ")
}

func (windowsPlatform) ApplyService(contract ServiceContract) error {
	manager, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer manager.Disconnect()
	service, err := manager.OpenService(ServiceName)
	if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
		service, err = manager.CreateService(ServiceName, contract.Executable, serviceConfig(contract), contract.Arguments...)
	} else if err == nil {
		err = service.UpdateConfig(serviceConfig(contract))
	}
	if err != nil {
		return err
	}
	defer service.Close()
	if err := service.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: 5 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 10 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 60 * time.Second},
	}, 24*60*60); err != nil {
		return err
	}
	return service.SetRecoveryActionsOnNonCrashFailures(true)
}

func (windowsPlatform) DeleteService() error {
	manager, service, err := connectService()
	if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
		return nil
	}
	if err != nil {
		return err
	}
	defer manager.Disconnect()
	defer service.Close()
	return service.Delete()
}

func (windowsPlatform) StartService() error {
	manager, service, err := connectService()
	if err != nil {
		return err
	}
	defer manager.Disconnect()
	defer service.Close()
	return service.Start()
}

func (windowsPlatform) StopService(timeout time.Duration) error {
	manager, service, err := connectService()
	if err != nil {
		return err
	}
	defer manager.Disconnect()
	defer service.Close()
	status, err := service.Query()
	if err != nil {
		return err
	}
	if status.State == svc.Stopped {
		return nil
	}
	if _, err := service.Control(svc.Stop); err != nil && !errors.Is(err, windows.ERROR_SERVICE_NOT_ACTIVE) {
		return err
	}
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		status, err = service.Query()
		if err != nil {
			return err
		}
		if status.State == svc.Stopped {
			return nil
		}
		time.Sleep(250 * time.Millisecond)
	}
	return fmt.Errorf("service did not stop within %s", timeout)
}

func (windowsPlatform) ServiceStatus() (ServiceStatus, error) {
	manager, service, err := connectService()
	if err != nil {
		return ServiceStatus{}, err
	}
	defer manager.Disconnect()
	defer service.Close()
	status, err := service.Query()
	if err != nil {
		return ServiceStatus{}, err
	}
	states := map[svc.State]string{
		svc.Stopped: "stopped", svc.StartPending: "start_pending", svc.StopPending: "stop_pending",
		svc.Running: "running", svc.ContinuePending: "continue_pending", svc.PausePending: "pause_pending", svc.Paused: "paused",
	}
	return ServiceStatus{State: states[status.State], PID: status.ProcessId}, nil
}

func (windowsPlatform) RunService(application ServiceApplication) error {
	isService, err := svc.IsWindowsService()
	if err != nil {
		return err
	}
	if !isService {
		return ErrNotService
	}
	return svc.Run(ServiceName, &serviceHandler{application: application})
}

type serviceHandler struct {
	application ServiceApplication
}

func (h *serviceHandler) Execute(_ []string, requests <-chan svc.ChangeRequest, changes chan<- svc.Status) (bool, uint32) {
	checkpoint := uint32(1)
	changes <- svc.Status{State: svc.StartPending, CheckPoint: checkpoint, WaitHint: 30000}
	err := h.application.Start(func(value uint32) {
		checkpoint = value
		changes <- svc.Status{State: svc.StartPending, CheckPoint: checkpoint, WaitHint: 30000}
	})
	if err != nil {
		return true, uint32(ExitCode(err))
	}
	changes <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}
	wait := make(chan error, 1)
	go func() { wait <- h.application.Wait() }()
	for {
		select {
		case err := <-wait:
			if err != nil {
				return true, uint32(ExitCode(err))
			}
			return false, 0
		case request := <-requests:
			switch request.Cmd {
			case svc.Interrogate:
				changes <- request.CurrentStatus
			case svc.Stop, svc.Shutdown:
				changes <- svc.Status{State: svc.StopPending, CheckPoint: 1, WaitHint: 15000}
				if err := h.application.Stop(10 * time.Second); err != nil {
					return false, 1
				}
				if err := <-wait; err != nil {
					return false, 1
				}
				return false, 0
			}
		}
	}
}

func (windowsPlatform) AddFirewallRule(port int) error {
	_ = exec.Command("netsh", "advfirewall", "firewall", "delete", "rule", "name="+FirewallRuleName).Run()
	command := exec.Command("netsh", "advfirewall", "firewall", "add", "rule",
		"name="+FirewallRuleName, "dir=in", "action=allow", "protocol=TCP", "localport="+strconv.Itoa(port), "profile=domain,private")
	output, err := command.CombinedOutput()
	if err != nil {
		return fmt.Errorf("netsh add firewall rule: %w: %s", err, strings.TrimSpace(string(output)))
	}
	return nil
}

func (windowsPlatform) RemoveFirewallRule() error {
	command := exec.Command("netsh", "advfirewall", "firewall", "delete", "rule", "name="+FirewallRuleName)
	output, err := command.CombinedOutput()
	if err != nil {
		return fmt.Errorf("netsh remove firewall rule: %w: %s", err, strings.TrimSpace(string(output)))
	}
	return nil
}

func (windowsPlatform) ReplaceFile(source, destination string) error {
	sourcePtr, err := windows.UTF16PtrFromString(source)
	if err != nil {
		return err
	}
	destinationPtr, err := windows.UTF16PtrFromString(destination)
	if err != nil {
		return err
	}
	result, _, callErr := procMoveFileEx.Call(
		uintptr(unsafe.Pointer(sourcePtr)), uintptr(unsafe.Pointer(destinationPtr)), moveFileReplaceExisting|moveFileWriteThrough,
	)
	if result == 0 {
		return fmt.Errorf("MoveFileExW %q to %q: %w", source, destination, callErr)
	}
	return nil
}

func (windowsPlatform) RemoveFileOnReboot(path string) error {
	pathPtr, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	result, _, callErr := procMoveFileEx.Call(uintptr(unsafe.Pointer(pathPtr)), 0, moveFileDelayUntilReboot)
	if result == 0 {
		return callErr
	}
	return nil
}

func (windowsPlatform) FQDN() (string, error) {
	size := uint32(256)
	buffer := make([]uint16, size)
	result, _, callErr := procGetComputerNameEx.Call(computerNameDNSFullyQualified, uintptr(unsafe.Pointer(&buffer[0])), uintptr(unsafe.Pointer(&size)))
	if result == 0 {
		return "", callErr
	}
	return windows.UTF16ToString(buffer[:size]), nil
}
