package config

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type LookupEnv func(string) (string, bool)

type Result struct {
	Config   Config
	Path     string
	Warnings []string
}

func ResolvePath(flagPath string, lookup LookupEnv) (string, error) {
	path := flagPath
	if path == "" {
		if value, ok := lookup("HA4WIN_CONFIG_FILE"); ok && strings.TrimSpace(value) != "" {
			path = value
		} else {
			path = DefaultPath()
		}
	}
	if filepath.IsAbs(path) {
		return filepath.Clean(path), nil
	}
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", fmt.Errorf("resolve config path: %w", err)
	}
	return absolute, nil
}

func Load(flagPath string, lookup LookupEnv) (Result, error) {
	path, err := ResolvePath(flagPath, lookup)
	if err != nil {
		return Result{}, err
	}
	defaults, err := toMap(Defaults())
	if err != nil {
		return Result{}, err
	}
	warnings := make([]string, 0)
	data, err := os.ReadFile(path)
	if err == nil {
		fileValues, decodeErr := decodeObject(data)
		if decodeErr != nil {
			return Result{}, fmt.Errorf("config file %q: %w", path, decodeErr)
		}
		if mergeErr := mergeMap(defaults, fileValues, "", &warnings); mergeErr != nil {
			return Result{}, mergeErr
		}
	} else if !os.IsNotExist(err) {
		return Result{}, fmt.Errorf("read config file %q: %w", path, err)
	}
	if err := applyEnvironment(defaults, "", lookup); err != nil {
		return Result{}, err
	}
	encoded, err := json.Marshal(defaults)
	if err != nil {
		return Result{}, fmt.Errorf("encode effective config: %w", err)
	}
	var cfg Config
	if err := json.Unmarshal(encoded, &cfg); err != nil {
		return Result{}, fmt.Errorf("decode effective config: %w", err)
	}
	return Result{Config: cfg, Path: path, Warnings: warnings}, nil
}

func Decode(data []byte) (Config, []string, error) {
	defaults, err := toMap(Defaults())
	if err != nil {
		return Config{}, nil, err
	}
	values, err := decodeObject(data)
	if err != nil {
		return Config{}, nil, err
	}
	warnings := make([]string, 0)
	if err := mergeMap(defaults, values, "", &warnings); err != nil {
		return Config{}, warnings, err
	}
	encoded, err := json.Marshal(defaults)
	if err != nil {
		return Config{}, warnings, err
	}
	var cfg Config
	if err := json.Unmarshal(encoded, &cfg); err != nil {
		return Config{}, warnings, err
	}
	return cfg, warnings, nil
}

func Marshal(cfg Config, redactToken bool) ([]byte, error) {
	if redactToken {
		cfg.API.Token = "***"
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("encode config: %w", err)
	}
	return append(data, '\n'), nil
}

func Patch(data []byte, updates map[string]any) ([]byte, error) {
	values, err := decodeObject(data)
	if err != nil {
		return nil, err
	}
	for path, value := range updates {
		parts := strings.Split(path, ".")
		current := values
		for _, part := range parts[:len(parts)-1] {
			next, ok := current[part].(map[string]any)
			if !ok {
				next = make(map[string]any)
				current[part] = next
			}
			current = next
		}
		current[parts[len(parts)-1]] = value
	}
	encoded, err := json.MarshalIndent(values, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("encode patched config: %w", err)
	}
	return append(encoded, '\n'), nil
}

func WriteFile(path string, cfg Config) error {
	data, err := Marshal(cfg, false)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("create config directory: %w", err)
	}
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, data, 0o600); err != nil {
		return fmt.Errorf("write config candidate: %w", err)
	}
	if err := os.Rename(temporary, path); err != nil {
		_ = os.Remove(temporary)
		return fmt.Errorf("promote config candidate: %w", err)
	}
	return nil
}

func toMap(cfg Config) (map[string]any, error) {
	data, err := json.Marshal(cfg)
	if err != nil {
		return nil, fmt.Errorf("encode defaults: %w", err)
	}
	return decodeObject(data)
}

func decodeObject(data []byte) (map[string]any, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var result map[string]any
	if err := decoder.Decode(&result); err != nil {
		return nil, err
	}
	if result == nil {
		return nil, fmt.Errorf("top-level value must be an object")
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			return nil, fmt.Errorf("multiple JSON values are not allowed")
		}
		return nil, err
	}
	return result, nil
}

func mergeMap(destination, source map[string]any, prefix string, warnings *[]string) error {
	for key, value := range source {
		path := key
		if prefix != "" {
			path = prefix + "." + key
		}
		expected, known := destination[key]
		if !known {
			*warnings = append(*warnings, "unknown configuration key: "+path)
			continue
		}
		expectedMap, expectsObject := expected.(map[string]any)
		valueMap, isObject := value.(map[string]any)
		if expectsObject {
			if !isObject {
				return fmt.Errorf("invalid type at %s: expected object", path)
			}
			if err := mergeMap(expectedMap, valueMap, path, warnings); err != nil {
				return err
			}
			continue
		}
		if isObject || !sameJSONType(expected, value) {
			return fmt.Errorf("invalid type at %s: expected %s", path, jsonType(expected))
		}
		destination[key] = value
	}
	return nil
}

func sameJSONType(expected, actual any) bool {
	switch expected.(type) {
	case bool:
		_, ok := actual.(bool)
		return ok
	case string:
		_, ok := actual.(string)
		return ok
	case json.Number:
		number, ok := actual.(json.Number)
		if !ok {
			return false
		}
		_, err := strconv.Atoi(string(number))
		return err == nil
	case []any:
		values, ok := actual.([]any)
		if !ok {
			return false
		}
		for _, value := range values {
			if _, ok := value.(string); !ok {
				return false
			}
		}
		return true
	default:
		return false
	}
}

func jsonType(value any) string {
	switch value.(type) {
	case bool:
		return "boolean"
	case string:
		return "string"
	case json.Number:
		return "integer"
	case []any:
		return "array of strings"
	default:
		return "value"
	}
}

func applyEnvironment(values map[string]any, prefix string, lookup LookupEnv) error {
	for key, value := range values {
		path := key
		if prefix != "" {
			path = prefix + "_" + key
		}
		if object, ok := value.(map[string]any); ok {
			if err := applyEnvironment(object, path, lookup); err != nil {
				return err
			}
			continue
		}
		name := "HA4WIN_" + strings.ToUpper(path)
		raw, present := lookup(name)
		if !present {
			continue
		}
		parsed, err := parseEnvironmentValue(raw, value)
		if err != nil {
			return fmt.Errorf("invalid value for %s (%s): %w", name, strings.ReplaceAll(path, "_", "."), err)
		}
		values[key] = parsed
	}
	return nil
}

func parseEnvironmentValue(raw string, expected any) (any, error) {
	switch expected.(type) {
	case string:
		return raw, nil
	case bool:
		switch strings.ToLower(strings.TrimSpace(raw)) {
		case "1", "true", "yes", "on":
			return true, nil
		case "0", "false", "no", "off":
			return false, nil
		default:
			return nil, fmt.Errorf("expected boolean")
		}
	case json.Number:
		value, err := strconv.Atoi(strings.TrimSpace(raw))
		if err != nil {
			return nil, fmt.Errorf("expected integer")
		}
		return json.Number(strconv.Itoa(value)), nil
	case []any:
		if strings.TrimSpace(raw) == "" {
			return []any{}, nil
		}
		parts := strings.Split(raw, ",")
		result := make([]any, 0, len(parts))
		for _, part := range parts {
			result = append(result, strings.TrimSpace(part))
		}
		return result, nil
	default:
		return nil, fmt.Errorf("unsupported type")
	}
}
