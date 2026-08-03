//go:build windows

package winapi

import (
	"errors"
	"fmt"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

const (
	wtsUserName                 = 5
	wtsDomainName               = 7
	invalidSessionID            = 0xffffffff
	shutdownReasonMajorOS       = 0x00020000
	shutdownReasonMinorReconfig = 0x00000004
	shutdownReasonPlanned       = 0x80000000
)

var (
	wtsapi32 = windows.NewLazySystemDLL("wtsapi32.dll")
	powrprof = windows.NewLazySystemDLL("powrprof.dll")

	procWTSDisconnectSession       = wtsapi32.NewProc("WTSDisconnectSession")
	procWTSQuerySessionInformation = wtsapi32.NewProc("WTSQuerySessionInformationW")
	procSetSuspendState            = powrprof.NewProc("SetSuspendState")
	procIsPwrHibernateAllowed      = powrprof.NewProc("IsPwrHibernateAllowed")
	procInitiateSystemShutdown     = advapi32.NewProc("InitiateSystemShutdownExW")
	procAbortSystemShutdown        = advapi32.NewProc("AbortSystemShutdownW")
	procOpenProcessTokenPower      = advapi32.NewProc("OpenProcessToken")
	procLookupPrivilegeValuePower  = advapi32.NewProc("LookupPrivilegeValueW")
	procAdjustTokenPrivilegesPower = advapi32.NewProc("AdjustTokenPrivileges")
)

func powerActuatorAvailable() (bool, string) { return true, "" }

func activeConsoleSession() (*ConsoleSession, error) {
	activeID := windows.WTSGetActiveConsoleSessionId()
	if activeID == invalidSessionID {
		return nil, nil
	}
	var sessions *windows.WTS_SESSION_INFO
	var count uint32
	if err := windows.WTSEnumerateSessions(0, 0, 1, &sessions, &count); err != nil {
		return nil, fmt.Errorf("WTSEnumerateSessionsW failed: %w", err)
	}
	if sessions == nil {
		return nil, nil
	}
	defer windows.WTSFreeMemory(uintptr(unsafe.Pointer(sessions)))
	items := unsafe.Slice(sessions, int(count))
	for _, item := range items {
		if item.SessionID != activeID {
			continue
		}
		user, err := querySessionString(activeID, wtsUserName)
		if err != nil {
			return nil, err
		}
		domain, err := querySessionString(activeID, wtsDomainName)
		if err != nil {
			return nil, err
		}
		if domain != "" && user != "" {
			user = domain + `\` + user
		}
		return &ConsoleSession{SessionID: activeID, User: user, State: wtsStateName(item.State)}, nil
	}
	return nil, nil
}

func querySessionString(sessionID, infoClass uint32) (string, error) {
	var buffer *uint16
	var bytes uint32
	result, _, callErr := procWTSQuerySessionInformation.Call(
		0, uintptr(sessionID), uintptr(infoClass),
		uintptr(unsafe.Pointer(&buffer)), uintptr(unsafe.Pointer(&bytes)),
	)
	if result == 0 {
		return "", fmt.Errorf("WTSQuerySessionInformationW failed: %w", nonzeroError(callErr))
	}
	if buffer == nil {
		return "", nil
	}
	defer windows.WTSFreeMemory(uintptr(unsafe.Pointer(buffer)))
	return windows.UTF16PtrToString(buffer), nil
}

func wtsDisconnectSession(sessionID uint32) error {
	result, _, callErr := procWTSDisconnectSession.Call(0, uintptr(sessionID), 1)
	if result == 0 {
		return fmt.Errorf("WTSDisconnectSession failed: %w", nonzeroError(callErr))
	}
	return nil
}

func hibernateSupported() (bool, error) {
	result, _, _ := procIsPwrHibernateAllowed.Call()
	return result != 0, nil
}

func setSuspendState(hibernate, force bool) error {
	result, _, callErr := procSetSuspendState.Call(boolValue(hibernate), boolValue(force), 0)
	if result == 0 {
		return fmt.Errorf("SetSuspendState failed: %w", nonzeroError(callErr))
	}
	return nil
}

func initiateSystemShutdown(reboot bool, delaySeconds uint32, force bool, message string) error {
	messagePtr, err := windows.UTF16PtrFromString(message)
	if err != nil {
		return fmt.Errorf("encode shutdown message: %w", err)
	}
	return withShutdownPrivilege(func() error {
		result, _, callErr := procInitiateSystemShutdown.Call(
			0, uintptr(unsafe.Pointer(messagePtr)), uintptr(delaySeconds), boolValue(force), boolValue(reboot),
			shutdownReasonMajorOS|shutdownReasonMinorReconfig|shutdownReasonPlanned,
		)
		if result == 0 {
			return fmt.Errorf("InitiateSystemShutdownExW failed: %w", nonzeroError(callErr))
		}
		return nil
	})
}

func abortSystemShutdown() error {
	return withShutdownPrivilege(func() error {
		result, _, callErr := procAbortSystemShutdown.Call(0)
		if result == 0 {
			return fmt.Errorf("AbortSystemShutdownW failed: %w", nonzeroError(callErr))
		}
		return nil
	})
}

func withShutdownPrivilege(operation func() error) (resultErr error) {
	var token windows.Token
	result, _, callErr := procOpenProcessTokenPower.Call(
		uintptr(windows.CurrentProcess()),
		windows.TOKEN_ADJUST_PRIVILEGES|windows.TOKEN_QUERY,
		uintptr(unsafe.Pointer(&token)),
	)
	if result == 0 {
		return fmt.Errorf("OpenProcessToken failed: %w", nonzeroError(callErr))
	}
	defer token.Close()

	name, err := windows.UTF16PtrFromString("SeShutdownPrivilege")
	if err != nil {
		return err
	}
	var luid windows.LUID
	result, _, callErr = procLookupPrivilegeValuePower.Call(0, uintptr(unsafe.Pointer(name)), uintptr(unsafe.Pointer(&luid)))
	if result == 0 {
		return fmt.Errorf("LookupPrivilegeValueW failed: %w", nonzeroError(callErr))
	}
	if err := adjustShutdownPrivilege(token, luid, windows.SE_PRIVILEGE_ENABLED); err != nil {
		return err
	}
	defer func() {
		if disableErr := adjustShutdownPrivilege(token, luid, 0); resultErr == nil && disableErr != nil {
			resultErr = fmt.Errorf("disable SeShutdownPrivilege: %w", disableErr)
		}
	}()
	return operation()
}

func adjustShutdownPrivilege(token windows.Token, luid windows.LUID, attributes uint32) error {
	privileges := windows.Tokenprivileges{PrivilegeCount: 1}
	privileges.Privileges[0] = windows.LUIDAndAttributes{Luid: luid, Attributes: attributes}
	result, _, callErr := procAdjustTokenPrivilegesPower.Call(
		uintptr(token), 0, uintptr(unsafe.Pointer(&privileges)), 0, 0, 0,
	)
	if result == 0 {
		return fmt.Errorf("AdjustTokenPrivileges failed: %w", nonzeroError(callErr))
	}
	if errors.Is(callErr, windows.ERROR_NOT_ALL_ASSIGNED) {
		return fmt.Errorf("AdjustTokenPrivileges failed: %w", windows.ERROR_NOT_ALL_ASSIGNED)
	}
	return nil
}

func wtsStateName(state uint32) string {
	names := []string{"active", "connected", "connect_query", "shadow", "disconnected", "idle", "listen", "reset", "down", "init"}
	if int(state) < len(names) {
		return names[state]
	}
	return "unknown"
}

func boolValue(value bool) uintptr {
	if value {
		return 1
	}
	return 0
}

func nonzeroError(err error) error {
	if err == nil || errors.Is(err, syscall.Errno(0)) {
		return syscall.EINVAL
	}
	return err
}
