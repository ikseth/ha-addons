package setup

import "github.com/ikseth/ha-addons/ha4win/internal/winapi"

func addFirewallRule(platform winapi.Platform, port int) error {
	return platform.AddFirewallRule(port)
}

func removeFirewallRule(platform winapi.Platform) error {
	return platform.RemoveFirewallRule()
}
