package main

import (
	"fmt"

	"github.com/ikseth/ha-addons/ha4win/internal/version"
)

func commandVersion(arguments []string) error {
	if len(arguments) != 0 {
		return fmt.Errorf("version does not accept arguments")
	}
	info := version.Current()
	fmt.Printf("ha4win %s (commit %s, built %s, channel %s, %s/%s)\n",
		info.APIVersion, info.Build.Commit, info.Build.Date, info.Build.Channel, info.Build.GoVersion, info.Build.Arch)
	return nil
}
