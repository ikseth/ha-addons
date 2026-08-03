package com

import (
	"context"
	"errors"
)

var ErrUnsupported = errors.New("COM is only supported on Windows")

type UpdatePackage struct {
	Title      string
	KB         string
	Severity   string
	SizeBytes  uint64
	IsSecurity bool
}

type UpdateSnapshot struct {
	Packages       []UpdatePackage
	RebootRequired bool
}

type DefenderStatus struct {
	AntivirusEnabled          bool
	RealtimeProtectionEnabled bool
	SignatureAgeDays          uint32
	SignatureVersion          string
	LastQuickScan             string
}

type BitLockerVolume struct {
	DriveLetter      string
	ProtectionStatus uint32
	ConversionStatus uint32
	EncryptionMethod uint32
}

func QueryUpdates(ctx context.Context, scope string) (UpdateSnapshot, error) {
	return queryUpdates(ctx, scope)
}

func QueryDefender(ctx context.Context) (DefenderStatus, error) {
	return queryDefender(ctx)
}

func QueryBitLocker(ctx context.Context) ([]BitLockerVolume, error) {
	return queryBitLocker(ctx)
}
