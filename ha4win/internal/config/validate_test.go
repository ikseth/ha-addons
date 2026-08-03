package config

import "testing"

func validConfig() Config {
	cfg := Defaults()
	cfg.API.Token = "01234567890123456789012345678901"
	cfg.TLS.Enabled = false
	cfg.API.BindHost = "127.0.0.1"
	return cfg
}

func TestValidate(t *testing.T) {
	if _, err := Validate(validConfig()); err != nil {
		t.Fatalf("valid config rejected: %v", err)
	}
	cases := []struct {
		name   string
		mutate func(*Config)
	}{
		{"empty token", func(cfg *Config) { cfg.API.Token = "" }},
		{"bad port", func(cfg *Config) { cfg.API.BindPort = 70000 }},
		{"bad CIDR", func(cfg *Config) { cfg.API.AllowedClients = []string{"192.0.2.1"} }},
		{"bad action", func(cfg *Config) { cfg.Actuators.Power.AllowedActions = []string{"reboot"} }},
		{"missing manifest", func(cfg *Config) { cfg.Management.RemoteUpdate.Enabled = true }},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			cfg := validConfig()
			test.mutate(&cfg)
			if _, err := Validate(cfg); err == nil {
				t.Fatal("invalid config was accepted")
			}
		})
	}
}

func TestLoopbackClassification(t *testing.T) {
	cases := map[string]bool{
		"127.0.0.1":  true,
		"127.8.9.10": true,
		"::1":        true,
		"::1%zone":   true,
		"0.0.0.0":    false,
		"::":         false,
		"192.0.2.1":  false,
	}
	for value, expected := range cases {
		if actual := IsLoopbackBind(value); actual != expected {
			t.Errorf("IsLoopbackBind(%q)=%v, want %v", value, actual, expected)
		}
	}
}
