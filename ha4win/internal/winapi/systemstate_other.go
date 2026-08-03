//go:build !windows

package winapi

import "time"

type unsupportedRegistryReader struct{}

func newRegistryReader() RegistryReader                                 { return unsupportedRegistryReader{} }
func (unsupportedRegistryReader) KeyExists(string) (bool, error)        { return false, ErrUnsupported }
func (unsupportedRegistryReader) String(string, string) (string, error) { return "", ErrUnsupported }
func (unsupportedRegistryReader) Strings(string, string) ([]string, error) {
	return nil, ErrUnsupported
}
func (unsupportedRegistryReader) DWORD(string, string) (uint32, error) { return 0, ErrUnsupported }
func getPowerStatus() (PowerStatus, error)                             { return PowerStatus{}, ErrUnsupported }
func getUptime() (time.Duration, error)                                { return 0, ErrUnsupported }
func shutdownPending() (bool, *string, error)                          { return false, nil, nil }
