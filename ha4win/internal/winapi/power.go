package winapi

type ConsoleSession struct {
	SessionID uint32
	User      string
	State     string
}

func PowerActuatorAvailable() (bool, string)         { return powerActuatorAvailable() }
func ActiveConsoleSession() (*ConsoleSession, error) { return activeConsoleSession() }
func WTSDisconnectSession(sessionID uint32) error    { return wtsDisconnectSession(sessionID) }
func HibernateSupported() (bool, error)              { return hibernateSupported() }
func SetSuspendState(hibernate, force bool) error    { return setSuspendState(hibernate, force) }
func InitiateSystemShutdown(reboot bool, delaySeconds uint32, force bool, message string) error {
	return initiateSystemShutdown(reboot, delaySeconds, force, message)
}
func AbortSystemShutdown() error { return abortSystemShutdown() }
