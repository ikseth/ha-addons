package update

import "time"

const (
	StateIdle        = "idle"
	StateChecking    = "checking"
	StateDownloading = "downloading"
	StateVerifying   = "verifying"
	StateApplying    = "applying"
	StateRestarting  = "restarting"
	StateRollback    = "rollback"
	StateError       = "error"
	StateDisabled    = "disabled"
)

var validTransitions = map[string]map[string]bool{
	StateIdle:        {StateChecking: true, StateDownloading: true, StateRollback: true, StateError: true, StateDisabled: true},
	StateChecking:    {StateIdle: true, StateDownloading: true, StateError: true},
	StateDownloading: {StateVerifying: true, StateError: true},
	StateVerifying:   {StateApplying: true, StateError: true},
	StateApplying:    {StateRestarting: true, StateRollback: true, StateError: true},
	StateRestarting:  {StateIdle: true, StateRollback: true, StateError: true},
	StateRollback:    {StateRestarting: true, StateIdle: true, StateError: true},
	StateError:       {StateChecking: true, StateDownloading: true, StateRollback: true, StateIdle: true, StateDisabled: true},
	StateDisabled:    {StateDisabled: true, StateIdle: true},
}

func CanTransition(from, to string) bool {
	return validTransitions[from][to]
}

type ManifestEntry struct {
	Version         string `json:"version"`
	ChangelogURL    string `json:"changelog_url,omitempty"`
	AssetURL        string `json:"asset_url"`
	SHA256          string `json:"sha256"`
	MinWindowsBuild uint32 `json:"min_windows_build,omitempty"`
}

type PreflightCheck struct {
	Name     string `json:"name"`
	OK       bool   `json:"ok"`
	Blocking bool   `json:"blocking"`
	Reason   string `json:"reason,omitempty"`
}

type Preflight struct {
	OK       bool             `json:"ok"`
	CanApply bool             `json:"can_apply"`
	Reason   *string          `json:"reason"`
	Checks   []PreflightCheck `json:"checks"`
}

type Status struct {
	OK                  bool       `json:"ok"`
	Supported           bool       `json:"supported"`
	Enabled             bool       `json:"enabled"`
	ReadonlyMode        bool       `json:"readonly_mode"`
	AllowInReadonly     bool       `json:"allow_in_readonly"`
	State               string     `json:"state"`
	InstalledVersion    string     `json:"installed_version"`
	TargetVersion       *string    `json:"target_version"`
	UpdateAvailable     bool       `json:"update_available"`
	Channel             string     `json:"channel"`
	ManifestURL         string     `json:"manifest_url"`
	ChangelogURL        *string    `json:"changelog_url"`
	AssetURL            *string    `json:"asset_url"`
	AssetSHA256         *string    `json:"asset_sha256"`
	LastCheckedAt       *time.Time `json:"last_checked_at"`
	LastAppliedAt       *time.Time `json:"last_applied_at"`
	LastError           *string    `json:"last_error"`
	Error               *string    `json:"error,omitempty"`
	SupportsApply       bool       `json:"supports_apply"`
	SupportsRollback    bool       `json:"supports_rollback"`
	SupportsApplyReason *string    `json:"supports_apply_reason"`
	RollbackVersion     *string    `json:"rollback_version"`
	Preflight           Preflight  `json:"preflight"`
}

type PersistentState struct {
	SchemaVersion    int        `json:"schema_version"`
	OperationID      string     `json:"operation_id"`
	Operation        string     `json:"operation"`
	State            string     `json:"state"`
	InstalledVersion string     `json:"installed_version"`
	TargetVersion    string     `json:"target_version"`
	StagedPath       string     `json:"staged_path,omitempty"`
	InstallPath      string     `json:"install_path"`
	PreviousPath     string     `json:"previous_path"`
	ConfigPath       string     `json:"config_path"`
	StartedAt        time.Time  `json:"started_at"`
	CompletedAt      *time.Time `json:"completed_at,omitempty"`
	Result           string     `json:"result,omitempty"`
	Error            string     `json:"error,omitempty"`
}
