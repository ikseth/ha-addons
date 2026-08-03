//go:build !windows

package winapi

func powerActuatorAvailable() (bool, string) { return false, ErrUnsupported.Error() }
func activeConsoleSession() (*ConsoleSession, error) {
	return nil, ErrUnsupported
}
func wtsDisconnectSession(uint32) error                       { return ErrUnsupported }
func hibernateSupported() (bool, error)                       { return false, ErrUnsupported }
func setSuspendState(bool, bool) error                        { return ErrUnsupported }
func initiateSystemShutdown(bool, uint32, bool, string) error { return ErrUnsupported }
func abortSystemShutdown() error                              { return ErrUnsupported }
