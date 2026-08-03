package api

import (
	"crypto/sha256"
	"crypto/subtle"
	"fmt"
	"net"
	"net/netip"
	"strings"
)

func TokenMatches(expected, presented string) bool {
	expectedHash := sha256.Sum256([]byte(expected))
	presentedHash := sha256.Sum256([]byte(presented))
	return subtle.ConstantTimeCompare(expectedHash[:], presentedHash[:]) == 1
}

func bearerToken(header string) (string, bool) {
	parts := strings.Fields(header)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		return "", false
	}
	return parts[1], true
}

func ParseAllowedClients(values []string) ([]netip.Prefix, error) {
	prefixes := make([]netip.Prefix, 0, len(values))
	for _, value := range values {
		prefix, err := netip.ParsePrefix(value)
		if err != nil {
			return nil, fmt.Errorf("invalid allowed client CIDR %q: %w", value, err)
		}
		if prefix.Addr().Is4In6() && prefix.Bits() >= 96 {
			prefix = netip.PrefixFrom(prefix.Addr().Unmap(), prefix.Bits()-96)
		}
		prefixes = append(prefixes, prefix.Masked())
	}
	return prefixes, nil
}

func PeerAllowed(remoteAddress string, prefixes []netip.Prefix) bool {
	if len(prefixes) == 0 {
		return true
	}
	host, _, err := net.SplitHostPort(remoteAddress)
	if err != nil {
		host = remoteAddress
	}
	if zone := strings.LastIndexByte(host, '%'); zone >= 0 {
		host = host[:zone]
	}
	address, err := netip.ParseAddr(strings.Trim(host, "[]"))
	if err != nil {
		return false
	}
	address = address.Unmap()
	for _, prefix := range prefixes {
		if prefix.Contains(address) {
			return true
		}
	}
	return false
}
