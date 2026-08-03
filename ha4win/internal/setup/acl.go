package setup

import "github.com/ikseth/ha-addons/ha4win/internal/winapi"

func applyDataDACL(platform winapi.Platform) error {
	return platform.ApplyRestrictedDACL(winapi.DataDirectory)
}
