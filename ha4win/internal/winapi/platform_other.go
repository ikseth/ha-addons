//go:build !windows

package winapi

import "time"

type unsupportedPlatform struct{}

func currentPlatform() Platform { return unsupportedPlatform{} }

func (unsupportedPlatform) IsElevated() (bool, error) { return false, ErrUnsupported }
func (unsupportedPlatform) IsSupportedWindows() (bool, string, error) {
	return false, "not windows", ErrUnsupported
}
func (unsupportedPlatform) ApplyRestrictedDACL(string) error    { return ErrUnsupported }
func (unsupportedPlatform) RestrictedDACL(string) (bool, error) { return false, ErrUnsupported }
func (unsupportedPlatform) InstallEventSource() error           { return ErrUnsupported }
func (unsupportedPlatform) RemoveEventSource() error            { return ErrUnsupported }
func (unsupportedPlatform) ServiceSnapshot() (ServiceSnapshot, error) {
	return ServiceSnapshot{}, ErrUnsupported
}
func (unsupportedPlatform) ApplyService(ServiceContract) error { return ErrUnsupported }
func (unsupportedPlatform) DeleteService() error               { return ErrUnsupported }
func (unsupportedPlatform) StartService() error                { return ErrUnsupported }
func (unsupportedPlatform) StopService(time.Duration) error    { return ErrUnsupported }
func (unsupportedPlatform) ServiceStatus() (ServiceStatus, error) {
	return ServiceStatus{}, ErrUnsupported
}
func (unsupportedPlatform) RunService(ServiceApplication) error { return ErrUnsupported }
func (unsupportedPlatform) AddFirewallRule(int) error           { return ErrUnsupported }
func (unsupportedPlatform) RemoveFirewallRule() error           { return ErrUnsupported }
func (unsupportedPlatform) ReplaceFile(string, string) error    { return ErrUnsupported }
func (unsupportedPlatform) RemoveFileOnReboot(string) error     { return ErrUnsupported }
func (unsupportedPlatform) FQDN() (string, error)               { return "", ErrUnsupported }
