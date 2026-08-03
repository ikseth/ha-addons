//go:build !windows

package winapi

func getSystemTimes() (CPUTimes, error)                  { return CPUTimes{}, ErrUnsupported }
func getProcessorPerformance() ([]CPUTimes, error)       { return nil, ErrUnsupported }
func getSystemPerformance() (CPUPerformance, error)      { return CPUPerformance{}, ErrUnsupported }
func getMemoryStatus() (MemoryStatus, error)             { return MemoryStatus{}, ErrUnsupported }
func getNetworkInterfaces() ([]NetworkInterface, error)  { return nil, ErrUnsupported }
func getLogicalDrives() ([]LogicalDrive, error)          { return nil, ErrUnsupported }
func getVolume(string) (VolumeInformation, error)        { return VolumeInformation{}, ErrUnsupported }
func queryService(string) (WatchedService, error)        { return WatchedService{}, ErrUnsupported }
func getWindowsInformation() (WindowsInformation, error) { return WindowsInformation{}, ErrUnsupported }
