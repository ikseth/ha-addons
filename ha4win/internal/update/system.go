package update

import (
	"context"
	"debug/pe"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type System interface {
	RunningUnderSCM() (bool, error)
	DirectoryWritable(string) bool
	FreeSpace(string) (uint64, error)
	WindowsBuild() (uint32, error)
	PendingReboot() (bool, error)
	VerifyAuthenticode(string) (bool, error)
	BinaryArchitecture(string) (string, error)
	LaunchDetached(string, []string) error
	TestBinaryVersion(context.Context, string) (string, error)
}

type nativeSystem struct{}

func NewNativeSystem() System { return nativeSystem{} }

func (nativeSystem) RunningUnderSCM() (bool, error)        { return platformRunningUnderSCM() }
func (nativeSystem) FreeSpace(path string) (uint64, error) { return platformFreeSpace(path) }
func (nativeSystem) WindowsBuild() (uint32, error)         { return platformWindowsBuild() }
func (nativeSystem) PendingReboot() (bool, error)          { return platformPendingReboot() }
func (nativeSystem) VerifyAuthenticode(path string) (bool, error) {
	return platformVerifyAuthenticode(path)
}
func (nativeSystem) BinaryArchitecture(path string) (string, error) {
	file, err := pe.Open(path)
	if err != nil {
		return "", fmt.Errorf("inspect staged PE executable: %w", err)
	}
	defer file.Close()
	switch file.FileHeader.Machine {
	case 0x8664:
		return "amd64", nil
	case 0xaa64:
		return "arm64", nil
	case 0x014c:
		return "386", nil
	default:
		return "", fmt.Errorf("staged PE executable uses unsupported machine type 0x%x", file.FileHeader.Machine)
	}
}
func (nativeSystem) LaunchDetached(executable string, arguments []string) error {
	return platformLaunchDetached(executable, arguments)
}

func (nativeSystem) DirectoryWritable(directory string) bool {
	file, err := os.CreateTemp(directory, ".ha4win-write-test-*")
	if err != nil {
		return false
	}
	name := file.Name()
	if err := file.Close(); err != nil {
		_ = os.Remove(name)
		return false
	}
	return os.Remove(name) == nil
}

func (nativeSystem) TestBinaryVersion(ctx context.Context, executable string) (string, error) {
	command := exec.CommandContext(ctx, executable, "version")
	output, err := command.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("staged binary version command failed: %w: %s", err, strings.TrimSpace(string(output)))
	}
	fields := strings.Fields(string(output))
	if len(fields) < 2 || fields[0] != "ha4win" {
		return "", fmt.Errorf("staged binary returned an invalid version response")
	}
	return fields[1], nil
}

func ensureDirectory(path string) error {
	if err := os.MkdirAll(path, 0o700); err != nil {
		return fmt.Errorf("create update directory %q: %w", path, err)
	}
	return nil
}

func waitBeforeServiceStop() {
	// Give the API response a short opportunity to reach the caller before the
	// independent applier stops the service process.
	time.Sleep(time.Second)
}

func cleanStagingPath(updateDirectory string) string {
	return filepath.Join(updateDirectory, "staging")
}
