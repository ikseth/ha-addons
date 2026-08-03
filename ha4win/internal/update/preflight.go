package update

import (
	"fmt"
	"strings"
)

type PreflightInput struct {
	RunningUnderSCM   bool
	InstallWritable   bool
	FreeBytes         uint64
	ArtifactBytes     uint64
	UpdateInProgress  bool
	AssetURL          string
	HostArchitecture  string
	AssetArchitecture string
	WindowsBuild      uint32
	MinWindowsBuild   uint32
	ReadonlyMode      bool
	AllowInReadonly   bool
	RequireSigned     bool
	SignatureValid    bool
	PendingReboot     bool
}

func EvaluatePreflight(input PreflightInput) Preflight {
	checks := []PreflightCheck{
		check("running_under_scm", input.RunningUnderSCM, true, "agent is not running as a service under the Windows SCM"),
		check("install_directory_writable", input.InstallWritable, true, "installation directory is not writable"),
		check("no_update_in_progress", !input.UpdateInProgress, true, "another update is already in progress"),
		check("asset_present", strings.TrimSpace(input.AssetURL) != "", true, "manifest does not provide an update asset"),
		check("architecture_matches", input.AssetArchitecture == "" || input.AssetArchitecture == input.HostArchitecture, true,
			fmt.Sprintf("asset architecture %s does not match host architecture %s", input.AssetArchitecture, input.HostArchitecture)),
		check("windows_build_supported", input.MinWindowsBuild == 0 || input.WindowsBuild >= input.MinWindowsBuild, true,
			fmt.Sprintf("Windows build %d is below required build %d", input.WindowsBuild, input.MinWindowsBuild)),
		check("readonly_mode_allows_update", !input.ReadonlyMode || input.AllowInReadonly, true, "readonly mode blocks remote updates"),
	}
	if input.ArtifactBytes > 0 {
		required := input.ArtifactBytes * 3
		checks = append(checks, check("disk_space", input.FreeBytes >= required, true,
			fmt.Sprintf("update directory has %d bytes free; %d bytes are required", input.FreeBytes, required)))
	} else {
		checks = append(checks, PreflightCheck{Name: "disk_space", OK: true, Blocking: true, Reason: "artifact size will be checked after download"})
	}
	if input.RequireSigned {
		checks = append(checks, check("authenticode_signature", input.SignatureValid, true, "asset does not have a valid Authenticode signature"))
	} else {
		checks = append(checks, PreflightCheck{Name: "authenticode_signature", OK: true, Blocking: true, Reason: "signature verification is disabled"})
	}
	checks = append(checks, PreflightCheck{
		Name: "pending_reboot", OK: !input.PendingReboot, Blocking: false,
		Reason: reasonIf(input.PendingReboot, "Windows reports a pending reboot"),
	})

	result := Preflight{OK: true, CanApply: true, Checks: checks}
	for _, current := range checks {
		if current.Blocking && !current.OK {
			result.OK = false
			result.CanApply = false
			if result.Reason == nil {
				reason := current.Reason
				result.Reason = &reason
			}
		}
	}
	return result
}

func check(name string, ok, blocking bool, failure string) PreflightCheck {
	return PreflightCheck{Name: name, OK: ok, Blocking: blocking, Reason: reasonIf(!ok, failure)}
}

func reasonIf(condition bool, reason string) string {
	if condition {
		return reason
	}
	return ""
}

func AssetArchitecture(assetURL string) string {
	lower := strings.ToLower(assetURL)
	for _, arch := range []string{"amd64", "arm64", "386"} {
		if strings.Contains(lower, "windows-"+arch) {
			return arch
		}
	}
	return ""
}
