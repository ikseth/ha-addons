package config

type Config struct {
	API          APIConfig        `json:"api"`
	TLS          TLSConfig        `json:"tls"`
	Modules      ModulesConfig    `json:"modules"`
	Actuators    ActuatorsConfig  `json:"actuators"`
	Management   ManagementConfig `json:"management"`
	ReadonlyMode bool             `json:"readonly_mode"`
	Logging      LoggingConfig    `json:"logging"`
}

type APIConfig struct {
	BindHost         string   `json:"bind_host"`
	BindPort         int      `json:"bind_port"`
	Token            string   `json:"token"`
	AllowedClients   []string `json:"allowed_clients"`
	SensorTimeoutSec int      `json:"sensor_timeout_sec"`
}

type TLSConfig struct {
	Enabled    bool             `json:"enabled"`
	CertFile   string           `json:"certfile"`
	KeyFile    string           `json:"keyfile"`
	SelfSigned SelfSignedConfig `json:"self_signed"`
}

type SelfSignedConfig struct {
	AutoGenerate    bool     `json:"auto_generate"`
	ValidDays       int      `json:"valid_days"`
	SubjectAltNames []string `json:"subject_alt_names"`
}

type ModulesConfig struct {
	CPU         CPUConfig        `json:"cpu"`
	Memory      EnabledConfig    `json:"memory"`
	Network     NetworkConfig    `json:"network"`
	Volumes     VolumesConfig    `json:"volumes"`
	Services    ServicesConfig   `json:"services"`
	SystemInfo  SystemInfoConfig `json:"system_info"`
	Maintenance EnabledConfig    `json:"maintenance"`
	Security    SecurityConfig   `json:"security"`
}

type EnabledConfig struct {
	Enabled bool `json:"enabled"`
}

type CPUConfig struct {
	Enabled bool `json:"enabled"`
	PerCore bool `json:"per_core"`
}

type NetworkConfig struct {
	Enabled           bool     `json:"enabled"`
	IncludeInterfaces []string `json:"include_interfaces"`
	ExcludeInterfaces []string `json:"exclude_interfaces"`
	AggregateMode     string   `json:"aggregate_mode"`
}

type VolumesConfig struct {
	Enabled           bool     `json:"enabled"`
	IncludeDriveTypes []string `json:"include_drive_types"`
	ExcludeMounts     []string `json:"exclude_mounts"`
}

type ServicesConfig struct {
	Enabled   bool     `json:"enabled"`
	Watchlist []string `json:"watchlist"`
}

type SystemInfoConfig struct {
	Enabled                 bool   `json:"enabled"`
	UpdatesEnabled          bool   `json:"updates_enabled"`
	UpdatesProvider         string `json:"updates_provider"`
	UpdatesSearchScope      string `json:"updates_search_scope"`
	UpdatesCheckIntervalSec int    `json:"updates_check_interval_sec"`
	UpdatesTimeoutSec       int    `json:"updates_timeout_sec"`
	UpdatesMaxPackages      int    `json:"updates_max_packages"`
}

type SecurityConfig struct {
	Enabled            bool `json:"enabled"`
	Defender           bool `json:"defender"`
	Firewall           bool `json:"firewall"`
	BitLocker          bool `json:"bitlocker"`
	RefreshIntervalSec int  `json:"refresh_interval_sec"`
}

type ActuatorsConfig struct {
	Power PowerConfig `json:"power"`
}

type PowerConfig struct {
	Enabled             bool     `json:"enabled"`
	AllowedActions      []string `json:"allowed_actions"`
	DefaultDelaySeconds int      `json:"default_delay_seconds"`
}

type ManagementConfig struct {
	RemoteUpdate RemoteUpdateConfig `json:"remote_update"`
}

type RemoteUpdateConfig struct {
	Enabled               bool   `json:"enabled"`
	ManifestURL           string `json:"manifest_url"`
	Channel               string `json:"channel"`
	CheckIntervalSec      int    `json:"check_interval_sec"`
	CheckTimeoutSec       int    `json:"check_timeout_sec"`
	ApplyTimeoutSec       int    `json:"apply_timeout_sec"`
	AllowInReadonly       bool   `json:"allow_in_readonly"`
	RequireSignedAsset    bool   `json:"require_signed_asset"`
	HealthCheckTimeoutSec int    `json:"health_check_timeout_sec"`
}

type LoggingConfig struct {
	Level           string `json:"level"`
	FileEnabled     bool   `json:"file_enabled"`
	MaxSizeMB       int    `json:"max_size_mb"`
	MaxFiles        int    `json:"max_files"`
	EventLogEnabled bool   `json:"eventlog_enabled"`
}
