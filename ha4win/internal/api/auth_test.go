package api

import "testing"

func TestTokenMatches(t *testing.T) {
	if !TokenMatches("correct-token", "correct-token") {
		t.Fatal("equal tokens did not match")
	}
	for _, candidate := range []string{"", "wrong-token", "correct-token-extra"} {
		if TokenMatches("correct-token", candidate) {
			t.Fatalf("unexpected match for %q", candidate)
		}
	}
}

func TestPeerAllowedIPv4IPv6AndMapped(t *testing.T) {
	prefixes, err := ParseAllowedClients([]string{"192.0.2.0/24", "2001:db8:abcd::/48"})
	if err != nil {
		t.Fatal(err)
	}
	cases := map[string]bool{
		"192.0.2.4:1234":          true,
		"[::ffff:192.0.2.4]:1234": true,
		"[2001:db8:abcd::5]:1234":    true,
		"[2001:db8::5]:1234":         false,
		"192.168.51.4:1234":          false,
		"not-an-address":             false,
	}
	for peer, expected := range cases {
		if actual := PeerAllowed(peer, prefixes); actual != expected {
			t.Errorf("PeerAllowed(%q)=%v, want %v", peer, actual, expected)
		}
	}
}

func TestPeerAllowedIPv6Zone(t *testing.T) {
	prefixes, err := ParseAllowedClients([]string{"fe80::/10"})
	if err != nil {
		t.Fatal(err)
	}
	if !PeerAllowed("[fe80::1%12]:8099", prefixes) {
		t.Fatal("zoned IPv6 peer was not normalized")
	}
}
