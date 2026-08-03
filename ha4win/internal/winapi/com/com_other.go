//go:build !windows

package com

import "context"

func queryUpdates(context.Context, string) (UpdateSnapshot, error) {
	return UpdateSnapshot{}, ErrUnsupported
}

func queryDefender(context.Context) (DefenderStatus, error) {
	return DefenderStatus{}, ErrUnsupported
}

func queryBitLocker(context.Context) ([]BitLockerVolume, error) {
	return nil, ErrUnsupported
}
