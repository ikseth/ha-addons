package version

import "testing"

func TestDevelopmentDefaults(t *testing.T) {
	info := Current()
	if info.APIVersion != "0.1.0-dev" || info.Build.Commit != "unknown" || info.Build.Date != "unknown" || info.Build.Channel != "dev" {
		t.Fatalf("unexpected development defaults: %+v", info)
	}
	if info.Platform != "windows" || info.Build.GoVersion == "" || info.Build.Arch == "" {
		t.Fatalf("incomplete version information: %+v", info)
	}
}
