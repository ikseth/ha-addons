package setup

import "github.com/ikseth/ha-addons/ha4win/internal/winapi"

func registerEventSource(platform winapi.Platform) error {
	return platform.InstallEventSource()
}

func removeEventSource(platform winapi.Platform) error {
	return platform.RemoveEventSource()
}
