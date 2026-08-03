//go:build windows

package update

import (
	"errors"
	"fmt"
	"os/exec"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

const (
	detachedProcess = 0x00000008
)

var updateKernel32 = windows.NewLazySystemDLL("kernel32.dll")
var updateNtdll = windows.NewLazySystemDLL("ntdll.dll")
var procGetDiskFreeSpaceEx = updateKernel32.NewProc("GetDiskFreeSpaceExW")
var procUpdateRtlGetVersion = updateNtdll.NewProc("RtlGetVersion")

type updateVersionInfo struct {
	Size        uint32
	Major       uint32
	Minor       uint32
	Build       uint32
	PlatformID  uint32
	ServicePack [128]uint16
}

func platformRunningUnderSCM() (bool, error) {
	isService, err := svc.IsWindowsService()
	if err != nil || isService {
		return isService, err
	}
	manager, err := mgr.Connect()
	if err != nil {
		return false, err
	}
	defer manager.Disconnect()
	service, err := manager.OpenService("ha4win")
	if err != nil {
		return false, nil
	}
	defer service.Close()
	status, err := service.Query()
	if err != nil {
		return false, err
	}
	return status.State == svc.Running, nil
}

func platformFreeSpace(path string) (uint64, error) {
	absolute, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return 0, err
	}
	var available uint64
	result, _, callErr := procGetDiskFreeSpaceEx.Call(uintptr(unsafe.Pointer(absolute)), uintptr(unsafe.Pointer(&available)), 0, 0)
	if result == 0 {
		return 0, fmt.Errorf("GetDiskFreeSpaceExW: %w", callErr)
	}
	return available, nil
}

func platformWindowsBuild() (uint32, error) {
	info := updateVersionInfo{Size: uint32(unsafe.Sizeof(updateVersionInfo{}))}
	status, _, _ := procUpdateRtlGetVersion.Call(uintptr(unsafe.Pointer(&info)))
	if status != 0 {
		return 0, fmt.Errorf("RtlGetVersion failed with NTSTATUS 0x%x", status)
	}
	return info.Build, nil
}

func platformPendingReboot() (bool, error) {
	paths := []string{
		`SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending`,
		`SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired`,
	}
	for _, path := range paths {
		key, err := registry.OpenKey(registry.LOCAL_MACHINE, path, registry.QUERY_VALUE|registry.WOW64_64KEY)
		if err == nil {
			key.Close()
			return true, nil
		}
		if !errors.Is(err, windows.ERROR_FILE_NOT_FOUND) && !errors.Is(err, windows.ERROR_PATH_NOT_FOUND) {
			return false, err
		}
	}
	return false, nil
}

func platformVerifyAuthenticode(string) (bool, error) {
	// The optional policy is disabled by default. Keeping an explicit blocking
	// result here prevents require_signed_asset from silently accepting an asset
	// until the WinVerifyTrust policy is implemented and validated on Windows.
	return false, fmt.Errorf("Authenticode verification is not available in this release")
}

func platformLaunchDetached(executable string, arguments []string) error {
	command := exec.Command(executable, arguments...)
	command.Stdin = nil
	command.Stdout = nil
	command.Stderr = nil
	command.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: windows.CREATE_NEW_PROCESS_GROUP | detachedProcess,
		HideWindow:    true,
	}
	if err := command.Start(); err != nil {
		return fmt.Errorf("launch detached updater: %w", err)
	}
	if command.Process != nil {
		_ = command.Process.Release()
	}
	return nil
}
