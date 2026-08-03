//go:build windows

package winapi

import (
	"errors"
	"fmt"
	"os"
	"runtime"
	"strings"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

const (
	systemProcessorPerformanceInformation = 8
	ifTypeSoftwareLoopback                = 24
	ifTypeTunnel                          = 131
	interfaceAndOperStatusHardware        = 1 << 0
	ndisPhysicalMediumWirelessLAN         = 1
	ndisPhysicalMediumNative80211         = 9
	ndisPhysicalMedium8023                = 14
	computerNameDNSDomain                 = 2
)

var (
	psapi32  = windows.NewLazySystemDLL("psapi.dll")
	iphlpapi = windows.NewLazySystemDLL("iphlpapi.dll")

	procGetSystemTimesTelemetry    = kernel32.NewProc("GetSystemTimes")
	procGlobalMemoryStatusEx       = kernel32.NewProc("GlobalMemoryStatusEx")
	procGetPerformanceInfo         = psapi32.NewProc("GetPerformanceInfo")
	procGetIfTable2                = iphlpapi.NewProc("GetIfTable2")
	procNtQuerySystemInformation   = ntdll.NewProc("NtQuerySystemInformation")
	procGetServiceKeyName          = advapi32.NewProc("GetServiceKeyNameW")
	procGetComputerNameExTelemetry = kernel32.NewProc("GetComputerNameExW")
)

type performanceInformation struct {
	Size              uint32
	CommitTotal       uintptr
	CommitLimit       uintptr
	CommitPeak        uintptr
	PhysicalTotal     uintptr
	PhysicalAvailable uintptr
	SystemCache       uintptr
	KernelTotal       uintptr
	KernelPaged       uintptr
	KernelNonpaged    uintptr
	PageSize          uintptr
	HandleCount       uint32
	ProcessCount      uint32
	ThreadCount       uint32
}

type memoryStatusEx struct {
	Length            uint32
	MemoryLoad        uint32
	TotalPhysical     uint64
	AvailablePhysical uint64
	TotalPageFile     uint64
	AvailablePageFile uint64
	TotalVirtual      uint64
	AvailableVirtual  uint64
	AvailableExtended uint64
}

type processorPerformanceInformation struct {
	IdleTime       int64
	KernelTime     int64
	UserTime       int64
	DpcTime        int64
	InterruptTime  int64
	InterruptCount uint32
}

func filetimeValue(value windows.Filetime) uint64 {
	return uint64(value.HighDateTime)<<32 | uint64(value.LowDateTime)
}

func getSystemTimes() (CPUTimes, error) {
	var idle windows.Filetime
	var kernel windows.Filetime
	var user windows.Filetime
	result, _, callErr := procGetSystemTimesTelemetry.Call(
		uintptr(unsafe.Pointer(&idle)), uintptr(unsafe.Pointer(&kernel)), uintptr(unsafe.Pointer(&user)),
	)
	if result == 0 {
		return CPUTimes{}, fmt.Errorf("GetSystemTimes failed: %w", callErr)
	}
	return CPUTimes{Idle: filetimeValue(idle), Kernel: filetimeValue(kernel), User: filetimeValue(user)}, nil
}

func getProcessorPerformance() ([]CPUTimes, error) {
	count := runtime.NumCPU()
	if count < 1 {
		count = 1
	}
	entries := make([]processorPerformanceInformation, count)
	for {
		var returned uint32
		status, _, _ := procNtQuerySystemInformation.Call(
			systemProcessorPerformanceInformation,
			uintptr(unsafe.Pointer(&entries[0])),
			uintptr(len(entries))*unsafe.Sizeof(entries[0]),
			uintptr(unsafe.Pointer(&returned)),
		)
		if uint32(status) == uint32(0xc0000004) && returned > uint32(len(entries))*uint32(unsafe.Sizeof(entries[0])) {
			entries = make([]processorPerformanceInformation, (returned+uint32(unsafe.Sizeof(entries[0]))-1)/uint32(unsafe.Sizeof(entries[0])))
			continue
		}
		if status != 0 {
			return nil, fmt.Errorf("NtQuerySystemInformation failed with NTSTATUS 0x%x", uint32(status))
		}
		used := int(returned / uint32(unsafe.Sizeof(entries[0])))
		if used == 0 || used > len(entries) {
			used = len(entries)
		}
		result := make([]CPUTimes, used)
		for index := range result {
			result[index] = CPUTimes{
				Idle: uint64(entries[index].IdleTime), Kernel: uint64(entries[index].KernelTime), User: uint64(entries[index].UserTime),
			}
		}
		return result, nil
	}
}

func performanceInfo() (performanceInformation, error) {
	info := performanceInformation{Size: uint32(unsafe.Sizeof(performanceInformation{}))}
	result, _, callErr := procGetPerformanceInfo.Call(uintptr(unsafe.Pointer(&info)), uintptr(info.Size))
	if result == 0 {
		return performanceInformation{}, fmt.Errorf("GetPerformanceInfo failed: %w", callErr)
	}
	return info, nil
}

func getSystemPerformance() (CPUPerformance, error) {
	info, err := performanceInfo()
	if err != nil {
		return CPUPerformance{}, err
	}
	return CPUPerformance{Processes: info.ProcessCount, Threads: info.ThreadCount, Handles: info.HandleCount}, nil
}

func getMemoryStatus() (MemoryStatus, error) {
	memory := memoryStatusEx{Length: uint32(unsafe.Sizeof(memoryStatusEx{}))}
	result, _, callErr := procGlobalMemoryStatusEx.Call(uintptr(unsafe.Pointer(&memory)))
	if result == 0 {
		return MemoryStatus{}, fmt.Errorf("GlobalMemoryStatusEx failed: %w", callErr)
	}
	performance, err := performanceInfo()
	if err != nil {
		return MemoryStatus{}, err
	}
	return MemoryStatus{
		TotalPhysical: memory.TotalPhysical, AvailablePhysical: memory.AvailablePhysical,
		CommitTotal: uint64(performance.CommitTotal) * uint64(performance.PageSize),
		CommitLimit: uint64(performance.CommitLimit) * uint64(performance.PageSize),
	}, nil
}

func getNetworkInterfaces() ([]NetworkInterface, error) {
	var table *windows.MibIfTable2
	result, _, _ := procGetIfTable2.Call(uintptr(unsafe.Pointer(&table)))
	if result != 0 {
		return nil, fmt.Errorf("GetIfTable2 failed with error %d", result)
	}
	if table == nil {
		return []NetworkInterface{}, nil
	}
	defer windows.FreeMibTable(unsafe.Pointer(table))
	rows := unsafe.Slice(&table.Table[0], int(table.NumEntries))
	interfaces := make([]NetworkInterface, 0, len(rows))
	for index := range rows {
		row := &rows[index]
		addressLength := min(int(row.PhysicalAddressLength), len(row.PhysicalAddress))
		speed := max(row.ReceiveLinkSpeed, row.TransmitLinkSpeed)
		interfaces = append(interfaces, NetworkInterface{
			Alias: windows.UTF16ToString(row.Alias[:]), Description: windows.UTF16ToString(row.Description[:]),
			MAC: formatMAC(row.PhysicalAddress[:addressLength]), OperStatus: interfaceStatus(row.OperStatus),
			SpeedMbps: speed / 1_000_000, Type: interfaceType(row.Type, row.PhysicalMediumType),
			RXBytes: row.InOctets, TXBytes: row.OutOctets,
			Hardware: row.InterfaceAndOperStatusFlags&interfaceAndOperStatusHardware != 0,
			Loopback: row.Type == ifTypeSoftwareLoopback, Tunnel: row.Type == ifTypeTunnel,
		})
	}
	return interfaces, nil
}

func formatMAC(address []byte) string {
	parts := make([]string, len(address))
	for index, value := range address {
		parts[index] = fmt.Sprintf("%02X", value)
	}
	return strings.Join(parts, ":")
}

func interfaceStatus(status uint32) string {
	switch status {
	case windows.IfOperStatusUp:
		return "up"
	case windows.IfOperStatusDown:
		return "down"
	case windows.IfOperStatusTesting:
		return "testing"
	case windows.IfOperStatusDormant:
		return "dormant"
	case windows.IfOperStatusNotPresent:
		return "not_present"
	case windows.IfOperStatusLowerLayerDown:
		return "lower_layer_down"
	default:
		return "unknown"
	}
}

func interfaceType(interfaceType, physicalMedium uint32) string {
	if interfaceType == 71 {
		return "wifi"
	}
	if interfaceType == 6 {
		return "ethernet"
	}
	if interfaceType == ifTypeSoftwareLoopback {
		return "loopback"
	}
	if interfaceType == ifTypeTunnel {
		return "tunnel"
	}
	if physicalMedium == ndisPhysicalMediumWirelessLAN || physicalMedium == ndisPhysicalMediumNative80211 {
		return "wifi"
	}
	if physicalMedium == ndisPhysicalMedium8023 {
		return "ethernet"
	}
	return "other"
}

func getLogicalDrives() ([]LogicalDrive, error) {
	required, err := windows.GetLogicalDriveStrings(0, nil)
	if err != nil {
		return nil, fmt.Errorf("GetLogicalDriveStringsW size failed: %w", err)
	}
	buffer := make([]uint16, required+1)
	written, err := windows.GetLogicalDriveStrings(uint32(len(buffer)), &buffer[0])
	if err != nil {
		return nil, fmt.Errorf("GetLogicalDriveStringsW failed: %w", err)
	}
	drives := make([]LogicalDrive, 0)
	for start := 0; start < int(written); {
		end := start
		for end < int(written) && buffer[end] != 0 {
			end++
		}
		if end == start {
			break
		}
		root := windows.UTF16ToString(buffer[start:end])
		rootPointer, pointerErr := windows.UTF16PtrFromString(root)
		if pointerErr != nil {
			return nil, pointerErr
		}
		drives = append(drives, LogicalDrive{Root: root, Type: driveType(windows.GetDriveType(rootPointer))})
		start = end + 1
	}
	return drives, nil
}

func driveType(value uint32) string {
	switch value {
	case windows.DRIVE_FIXED:
		return "fixed"
	case windows.DRIVE_REMOVABLE:
		return "removable"
	case windows.DRIVE_REMOTE:
		return "network"
	case windows.DRIVE_CDROM:
		return "cdrom"
	case windows.DRIVE_RAMDISK:
		return "ramdisk"
	default:
		return "unknown"
	}
}

func getVolume(root string) (VolumeInformation, error) {
	rootPointer, err := windows.UTF16PtrFromString(root)
	if err != nil {
		return VolumeInformation{}, err
	}
	label := make([]uint16, windows.MAX_PATH+1)
	fileSystem := make([]uint16, windows.MAX_PATH+1)
	var flags uint32
	if err := windows.GetVolumeInformation(rootPointer, &label[0], uint32(len(label)), nil, nil, &flags, &fileSystem[0], uint32(len(fileSystem))); err != nil {
		return VolumeInformation{}, fmt.Errorf("GetVolumeInformationW %q failed: %w", root, err)
	}
	var available uint64
	var total uint64
	var free uint64
	if err := windows.GetDiskFreeSpaceEx(rootPointer, &available, &total, &free); err != nil {
		return VolumeInformation{}, fmt.Errorf("GetDiskFreeSpaceExW %q failed: %w", root, err)
	}
	return VolumeInformation{
		Label: windows.UTF16ToString(label), FileSystem: windows.UTF16ToString(fileSystem),
		ReadOnly: flags&windows.FILE_READ_ONLY_VOLUME != 0, TotalBytes: total, FreeBytes: free,
	}, nil
}

func queryService(requestedName string) (WatchedService, error) {
	manager, err := windows.OpenSCManager(nil, nil, windows.SC_MANAGER_CONNECT)
	if err != nil {
		return WatchedService{}, fmt.Errorf("OpenSCManagerW failed: %w", err)
	}
	defer windows.CloseServiceHandle(manager)
	serviceName := requestedName
	service, err := openServiceForQuery(manager, serviceName)
	if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
		serviceName, err = serviceKeyName(manager, requestedName)
		if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
			return WatchedService{Exists: false}, nil
		}
		if err == nil {
			service, err = openServiceForQuery(manager, serviceName)
		}
	}
	if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
		return WatchedService{Exists: false}, nil
	}
	if err != nil {
		return WatchedService{}, fmt.Errorf("OpenServiceW %q failed: %w", requestedName, err)
	}
	defer windows.CloseServiceHandle(service)

	var status windows.SERVICE_STATUS_PROCESS
	var needed uint32
	if err := windows.QueryServiceStatusEx(service, windows.SC_STATUS_PROCESS_INFO, (*byte)(unsafe.Pointer(&status)), uint32(unsafe.Sizeof(status)), &needed); err != nil {
		return WatchedService{}, fmt.Errorf("QueryServiceStatusEx %q failed: %w", serviceName, err)
	}
	configuration, err := serviceConfiguration(service)
	if err != nil {
		return WatchedService{}, fmt.Errorf("QueryServiceConfigW %q failed: %w", serviceName, err)
	}
	startType := serviceStartType(configuration.startType)
	if startType == "auto" {
		delayed, delayedErr := delayedAutoStart(service)
		if delayedErr != nil {
			return WatchedService{}, fmt.Errorf("QueryServiceConfig2W %q failed: %w", serviceName, delayedErr)
		}
		if delayed {
			startType = "auto_delayed"
		}
	}
	return WatchedService{
		Name: serviceName, DisplayName: configuration.displayName, Exists: true,
		Status: serviceState(status.CurrentState), StartType: startType, PID: status.ProcessId,
		CanStop: status.ControlsAccepted&windows.SERVICE_ACCEPT_STOP != 0, ExitCode: status.Win32ExitCode,
	}, nil
}

func openServiceForQuery(manager windows.Handle, name string) (windows.Handle, error) {
	pointer, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return 0, err
	}
	return windows.OpenService(manager, pointer, windows.SERVICE_QUERY_STATUS|windows.SERVICE_QUERY_CONFIG)
}

func serviceKeyName(manager windows.Handle, displayName string) (string, error) {
	displayPointer, err := windows.UTF16PtrFromString(displayName)
	if err != nil {
		return "", err
	}
	var size uint32
	result, _, callErr := procGetServiceKeyName.Call(uintptr(manager), uintptr(unsafe.Pointer(displayPointer)), 0, uintptr(unsafe.Pointer(&size)))
	if result == 0 && !errors.Is(callErr, windows.ERROR_INSUFFICIENT_BUFFER) {
		return "", callErr
	}
	buffer := make([]uint16, size+1)
	result, _, callErr = procGetServiceKeyName.Call(
		uintptr(manager), uintptr(unsafe.Pointer(displayPointer)), uintptr(unsafe.Pointer(&buffer[0])), uintptr(unsafe.Pointer(&size)),
	)
	if result == 0 {
		return "", callErr
	}
	return windows.UTF16ToString(buffer), nil
}

type queriedServiceConfiguration struct {
	displayName string
	startType   uint32
}

func serviceConfiguration(service windows.Handle) (queriedServiceConfiguration, error) {
	var needed uint32
	err := windows.QueryServiceConfig(service, nil, 0, &needed)
	if err != nil && !errors.Is(err, windows.ERROR_INSUFFICIENT_BUFFER) {
		return queriedServiceConfiguration{}, err
	}
	if needed < uint32(unsafe.Sizeof(windows.QUERY_SERVICE_CONFIG{})) {
		return queriedServiceConfiguration{}, fmt.Errorf("QueryServiceConfigW returned invalid buffer size %d", needed)
	}
	buffer := make([]byte, needed)
	configuration := (*windows.QUERY_SERVICE_CONFIG)(unsafe.Pointer(&buffer[0]))
	if err := windows.QueryServiceConfig(service, configuration, needed, &needed); err != nil {
		return queriedServiceConfiguration{}, err
	}
	return queriedServiceConfiguration{
		displayName: windows.UTF16PtrToString(configuration.DisplayName), startType: configuration.StartType,
	}, nil
}

func delayedAutoStart(service windows.Handle) (bool, error) {
	var value windows.SERVICE_DELAYED_AUTO_START_INFO
	var needed uint32
	err := windows.QueryServiceConfig2(service, windows.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, (*byte)(unsafe.Pointer(&value)), uint32(unsafe.Sizeof(value)), &needed)
	return value.IsDelayedAutoStartUp != 0, err
}

func serviceStartType(value uint32) string {
	switch value {
	case windows.SERVICE_AUTO_START:
		return "auto"
	case windows.SERVICE_DEMAND_START:
		return "manual"
	case windows.SERVICE_DISABLED:
		return "disabled"
	case windows.SERVICE_BOOT_START:
		return "boot"
	case windows.SERVICE_SYSTEM_START:
		return "system"
	default:
		return "unknown"
	}
}

func serviceState(value uint32) string {
	switch value {
	case windows.SERVICE_STOPPED:
		return "stopped"
	case windows.SERVICE_START_PENDING:
		return "start_pending"
	case windows.SERVICE_STOP_PENDING:
		return "stop_pending"
	case windows.SERVICE_RUNNING:
		return "running"
	case windows.SERVICE_CONTINUE_PENDING:
		return "continue_pending"
	case windows.SERVICE_PAUSE_PENDING:
		return "pause_pending"
	case windows.SERVICE_PAUSED:
		return "paused"
	default:
		return "unknown"
	}
}

func getWindowsInformation() (WindowsInformation, error) {
	version := windows.RtlGetVersion()
	key, err := registry.OpenKey(registry.LOCAL_MACHINE, `SOFTWARE\Microsoft\Windows NT\CurrentVersion`, registry.QUERY_VALUE|registry.WOW64_64KEY)
	if err != nil {
		return WindowsInformation{}, fmt.Errorf("open Windows version registry key: %w", err)
	}
	defer key.Close()
	productName, _, err := key.GetStringValue("ProductName")
	if err != nil {
		return WindowsInformation{}, fmt.Errorf("read ProductName: %w", err)
	}
	editionID, _, _ := key.GetStringValue("EditionID")
	displayVersion, _, _ := key.GetStringValue("DisplayVersion")
	currentBuild, _, err := key.GetStringValue("CurrentBuild")
	if err != nil {
		return WindowsInformation{}, fmt.Errorf("read CurrentBuild: %w", err)
	}
	ubr, _, _ := key.GetIntegerValue("UBR")
	installDate, _, _ := key.GetIntegerValue("InstallDate")
	hostname, err := os.Hostname()
	if err != nil {
		return WindowsInformation{}, fmt.Errorf("get hostname: %w", err)
	}
	domain, err := computerDomain()
	if err != nil {
		return WindowsInformation{}, err
	}
	joined := domain != ""
	if !joined {
		domain = "WORKGROUP"
	}
	return WindowsInformation{
		Hostname: hostname, ProductName: productName, EditionID: editionID, DisplayVersion: displayVersion, CurrentBuild: currentBuild,
		Major: version.MajorVersion, Minor: version.MinorVersion, BuildNumber: version.BuildNumber, UBR: uint32(ubr),
		InstallDate: time.Unix(int64(installDate), 0).UTC(), Uptime: windows.DurationSinceBoot(), Domain: domain, DomainJoined: joined,
	}, nil
}

func computerDomain() (string, error) {
	var size uint32
	result, _, callErr := procGetComputerNameExTelemetry.Call(computerNameDNSDomain, 0, uintptr(unsafe.Pointer(&size)))
	if result == 0 && !errors.Is(callErr, windows.ERROR_MORE_DATA) {
		return "", fmt.Errorf("GetComputerNameExW size failed: %w", callErr)
	}
	if size == 0 {
		return "", nil
	}
	buffer := make([]uint16, size)
	result, _, callErr = procGetComputerNameExTelemetry.Call(
		computerNameDNSDomain, uintptr(unsafe.Pointer(&buffer[0])), uintptr(unsafe.Pointer(&size)),
	)
	if result == 0 {
		return "", fmt.Errorf("GetComputerNameExW failed: %w", callErr)
	}
	return windows.UTF16ToString(buffer), nil
}
