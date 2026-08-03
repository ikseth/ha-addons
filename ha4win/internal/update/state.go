package update

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
)

func ReadPersistentState(path string) (PersistentState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return PersistentState{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var state PersistentState
	if err := decoder.Decode(&state); err != nil {
		return PersistentState{}, fmt.Errorf("decode update state: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return PersistentState{}, fmt.Errorf("update state has trailing data")
	}
	if state.SchemaVersion != 1 || state.OperationID == "" || state.Operation == "" {
		return PersistentState{}, fmt.Errorf("update state is incomplete or has an unsupported schema")
	}
	return state, nil
}

func WritePersistentState(path string, state PersistentState) error {
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("encode update state: %w", err)
	}
	data = append(data, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("create update state directory: %w", err)
	}
	temporary := path + ".tmp"
	file, err := os.OpenFile(temporary, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("create update state candidate: %w", err)
	}
	removeTemporary := true
	defer func() {
		_ = file.Close()
		if removeTemporary {
			_ = os.Remove(temporary)
		}
	}()
	if _, err := file.Write(data); err != nil {
		return fmt.Errorf("write update state candidate: %w", err)
	}
	if err := file.Sync(); err != nil {
		return fmt.Errorf("flush update state candidate: %w", err)
	}
	if err := file.Close(); err != nil {
		return fmt.Errorf("close update state candidate: %w", err)
	}
	if err := os.Rename(temporary, path); err != nil {
		return fmt.Errorf("promote update state candidate: %w", err)
	}
	removeTemporary = false
	return nil
}

type fileLock struct {
	path string
}

func acquireFileLock(path, operationID string) (*fileLock, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if os.IsExist(err) {
			return nil, fmt.Errorf("another update is already in progress")
		}
		return nil, fmt.Errorf("create update lock: %w", err)
	}
	if _, err := file.WriteString(strconv.Itoa(os.Getpid()) + " " + operationID + "\n"); err != nil {
		_ = file.Close()
		_ = os.Remove(path)
		return nil, fmt.Errorf("write update lock: %w", err)
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		_ = os.Remove(path)
		return nil, fmt.Errorf("flush update lock: %w", err)
	}
	if err := file.Close(); err != nil {
		_ = os.Remove(path)
		return nil, err
	}
	return &fileLock{path: path}, nil
}

func claimFileLock(path, operationID string) error {
	contents := []byte(strconv.Itoa(os.Getpid()) + " " + operationID + "\n")
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return fmt.Errorf("claim update lock: %w", err)
	}
	if _, err := file.Write(contents); err != nil {
		_ = file.Close()
		return fmt.Errorf("write claimed update lock: %w", err)
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return fmt.Errorf("flush claimed update lock: %w", err)
	}
	return file.Close()
}

func (lock *fileLock) Release() {
	if lock != nil {
		_ = os.Remove(lock.path)
	}
}
