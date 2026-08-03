package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func env(values map[string]string) LookupEnv {
	return func(name string) (string, bool) {
		value, ok := values[name]
		return value, ok
	}
}

func TestResolvePathPrecedence(t *testing.T) {
	directory := t.TempDir()
	flagPath := filepath.Join(directory, "flag.json")
	envPath := filepath.Join(directory, "environment.json")
	got, err := ResolvePath(flagPath, env(map[string]string{"HA4WIN_CONFIG_FILE": envPath}))
	if err != nil || got != flagPath {
		t.Fatalf("flag path did not win: path=%q err=%v", got, err)
	}
	got, err = ResolvePath("", env(map[string]string{"HA4WIN_CONFIG_FILE": envPath}))
	if err != nil || got != envPath {
		t.Fatalf("environment path was not selected: path=%q err=%v", got, err)
	}
}

func TestRecursiveMergeAndEnvironmentPrecedence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	data := `{
  "api": {"bind_port": 8100, "token": "file-token-that-is-long-enough"},
  "modules": {"network": {"exclude_interfaces": ["File*"]}}
}`
	if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}
	result, err := Load(path, env(map[string]string{
		"HA4WIN_API_BIND_PORT":                      "8200",
		"HA4WIN_MODULES_NETWORK_EXCLUDE_INTERFACES": "Env*,Second*",
		"HA4WIN_TLS_ENABLED":                        "false",
	}))
	if err != nil {
		t.Fatal(err)
	}
	if result.Config.API.BindPort != 8200 || result.Config.API.BindHost != "0.0.0.0" {
		t.Fatalf("leaf precedence or recursive default merge failed: %+v", result.Config.API)
	}
	want := []string{"Env*", "Second*"}
	if strings.Join(result.Config.Modules.Network.ExcludeInterfaces, ",") != strings.Join(want, ",") {
		t.Fatalf("list replacement failed: %#v", result.Config.Modules.Network.ExcludeInterfaces)
	}
}

func TestInvalidFileTypeIsFatal(t *testing.T) {
	_, _, err := Decode([]byte(`{"api":{"bind_port":"8099"}}`))
	if err == nil || !strings.Contains(err.Error(), "api.bind_port") {
		t.Fatalf("expected a path-specific type error, got %v", err)
	}
}

func TestInvalidEnvironmentTypeIsFatal(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.json")
	_, err := Load(path, env(map[string]string{"HA4WIN_API_BIND_PORT": "not-a-number"}))
	if err == nil || !strings.Contains(err.Error(), "HA4WIN_API_BIND_PORT") {
		t.Fatalf("expected environment type error, got %v", err)
	}
}

func TestUnknownKeysWarn(t *testing.T) {
	_, warnings, err := Decode([]byte(`{"api":{"future_option":true}}`))
	if err != nil {
		t.Fatal(err)
	}
	if len(warnings) != 1 || !strings.Contains(warnings[0], "api.future_option") {
		t.Fatalf("unexpected warnings: %#v", warnings)
	}
}

func TestPatchPreservesUnknownAndUnspecifiedValues(t *testing.T) {
	input := []byte(`{"api":{"token":"old","bind_port":9000},"future":{"value":true}}`)
	patched, err := Patch(input, map[string]any{"api.token": "new"})
	if err != nil {
		t.Fatal(err)
	}
	text := string(patched)
	for _, expected := range []string{`"token": "new"`, `"bind_port": 9000`, `"future"`, `"value": true`} {
		if !strings.Contains(text, expected) {
			t.Fatalf("patched config lost %s: %s", expected, text)
		}
	}
}
