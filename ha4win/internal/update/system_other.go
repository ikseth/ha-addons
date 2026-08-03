//go:build !windows

package update

import (
	"fmt"
	"syscall"
)

func platformRunningUnderSCM() (bool, error) { return false, nil }

func platformFreeSpace(path string) (uint64, error) {
	var status syscall.Statfs_t
	if err := syscall.Statfs(path, &status); err != nil {
		return 0, err
	}
	return status.Bavail * uint64(status.Bsize), nil
}

func platformWindowsBuild() (uint32, error) { return 0, nil }
func platformPendingReboot() (bool, error)  { return false, nil }
func platformVerifyAuthenticode(string) (bool, error) {
	return false, fmt.Errorf("Authenticode verification is only supported on Windows")
}
func platformLaunchDetached(string, []string) error {
	return fmt.Errorf("detached update application is only supported on Windows")
}
