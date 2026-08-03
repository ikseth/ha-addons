package update

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const maxManifestSize = 1024 * 1024

type manifestDocument struct {
	Channels map[string]ManifestEntry `json:"channels"`
	ManifestEntry
}

func ParseManifest(data []byte, channel, arch string) (ManifestEntry, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var document manifestDocument
	if err := decoder.Decode(&document); err != nil {
		return ManifestEntry{}, fmt.Errorf("manifest is not valid JSON: %w", err)
	}
	if err := ensureJSONEnd(decoder); err != nil {
		return ManifestEntry{}, err
	}
	entry := document.ManifestEntry
	if document.Channels != nil {
		selected, found := document.Channels[channel]
		if !found {
			return ManifestEntry{}, fmt.Errorf("manifest channel %q not found", channel)
		}
		entry = selected
	}
	entry.AssetURL = strings.ReplaceAll(entry.AssetURL, "{arch}", arch)
	if err := ValidateManifestEntry(entry, arch); err != nil {
		return ManifestEntry{}, err
	}
	return entry, nil
}

func ensureJSONEnd(decoder *json.Decoder) error {
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			return fmt.Errorf("manifest contains multiple JSON values")
		}
		return fmt.Errorf("manifest has trailing data: %w", err)
	}
	return nil
}

func ValidateManifestEntry(entry ManifestEntry, arch string) error {
	if _, err := parseSemanticVersion(entry.Version); err != nil {
		return fmt.Errorf("invalid target version: %w", err)
	}
	asset, err := url.Parse(strings.TrimSpace(entry.AssetURL))
	if err != nil || (asset.Scheme != "http" && asset.Scheme != "https") || asset.Host == "" {
		return fmt.Errorf("manifest asset_url must be an absolute HTTP or HTTPS URL")
	}
	if strings.Contains(entry.AssetURL, "{arch}") {
		return fmt.Errorf("manifest asset_url contains an unresolved architecture marker")
	}
	for _, candidate := range []string{"amd64", "arm64", "386"} {
		if strings.Contains(strings.ToLower(asset.Path), "windows-"+candidate) && candidate != arch {
			return fmt.Errorf("asset architecture %s does not match host architecture %s", candidate, arch)
		}
	}
	digest, err := hex.DecodeString(strings.TrimSpace(entry.SHA256))
	if err != nil || len(digest) != 32 {
		return fmt.Errorf("manifest sha256 must contain exactly 64 hexadecimal characters")
	}
	if entry.ChangelogURL != "" {
		changelog, err := url.Parse(entry.ChangelogURL)
		if err != nil || (changelog.Scheme != "http" && changelog.Scheme != "https") || changelog.Host == "" {
			return fmt.Errorf("manifest changelog_url must be an absolute HTTP or HTTPS URL")
		}
	}
	return nil
}

func FetchManifest(ctx context.Context, client *http.Client, manifestURL, channel, arch string, now time.Time) (ManifestEntry, error) {
	requestURL, err := cacheBustedURL(manifestURL, now)
	if err != nil {
		return ManifestEntry{}, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, requestURL, nil)
	if err != nil {
		return ManifestEntry{}, fmt.Errorf("create manifest request: %w", err)
	}
	request.Header.Set("Accept", "application/json")
	response, err := client.Do(request)
	if err != nil {
		return ManifestEntry{}, fmt.Errorf("manifest fetch failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return ManifestEntry{}, fmt.Errorf("manifest fetch returned HTTP %d", response.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, maxManifestSize+1))
	if err != nil {
		return ManifestEntry{}, fmt.Errorf("read manifest: %w", err)
	}
	if len(data) > maxManifestSize {
		return ManifestEntry{}, fmt.Errorf("manifest exceeds 1 MiB")
	}
	return ParseManifest(data, channel, arch)
}

func cacheBustedURL(raw string, now time.Time) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return "", fmt.Errorf("manifest URL must be an absolute HTTP or HTTPS URL")
	}
	query := parsed.Query()
	query.Set("ha4win_ts", fmt.Sprintf("%d", now.Unix()/30))
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}
