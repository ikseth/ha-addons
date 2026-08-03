package version

import "runtime"

var (
	Version   = "0.1.0-dev"
	Commit    = "unknown"
	BuildDate = "unknown"
	Channel   = "dev"
)

const (
	SchemaVersion         = "1.1"
	Platform              = "windows"
	MinIntegrationVersion = "0.1.0"
	MaxIntegrationVersion = "0.9.x"
)

type Build struct {
	Commit    string `json:"commit"`
	Date      string `json:"date"`
	Channel   string `json:"channel"`
	GoVersion string `json:"go_version"`
	Arch      string `json:"arch"`
}

type Info struct {
	APIVersion            string `json:"api_version"`
	SchemaVersion         string `json:"schema_version"`
	Platform              string `json:"platform"`
	MinIntegrationVersion string `json:"min_integration_version"`
	MaxIntegrationVersion string `json:"max_integration_version"`
	Build                 Build  `json:"build"`
}

func Current() Info {
	return Info{
		APIVersion:            Version,
		SchemaVersion:         SchemaVersion,
		Platform:              Platform,
		MinIntegrationVersion: MinIntegrationVersion,
		MaxIntegrationVersion: MaxIntegrationVersion,
		Build: Build{
			Commit:    Commit,
			Date:      BuildDate,
			Channel:   Channel,
			GoVersion: runtime.Version(),
			Arch:      runtime.GOARCH,
		},
	}
}
