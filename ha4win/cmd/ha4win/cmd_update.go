package main

import "fmt"

func commandUpdate(arguments []string) error {
	if len(arguments) != 1 || (arguments[0] != "apply" && arguments[0] != "rollback") {
		return fmt.Errorf("usage: ha4win update apply|rollback")
	}
	return fmt.Errorf("update %s is not implemented in Phase 0", arguments[0])
}
