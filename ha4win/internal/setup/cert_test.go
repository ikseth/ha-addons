package setup

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/x509"
	"encoding/pem"
	"net"
	"os"
	"path/filepath"
	"testing"
)

func TestGeneratedCertificateProfile(t *testing.T) {
	directory := t.TempDir()
	certPath := filepath.Join(directory, "ha4win.crt")
	keyPath := filepath.Join(directory, "ha4win.key")
	_, generated, err := EnsureCertificate(certPath, keyPath, 3650, []string{"extra.example", "192.0.2.10"}, false)
	if err != nil {
		t.Fatal(err)
	}
	if !generated {
		t.Fatal("certificate was not generated")
	}
	data, err := os.ReadFile(certPath)
	if err != nil {
		t.Fatal(err)
	}
	block, _ := pem.Decode(data)
	certificate, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	publicKey, ok := certificate.PublicKey.(*ecdsa.PublicKey)
	if !ok || publicKey.Curve != elliptic.P256() {
		t.Fatalf("unexpected public key: %#v", certificate.PublicKey)
	}
	if certificate.SignatureAlgorithm != x509.ECDSAWithSHA256 || certificate.IsCA {
		t.Fatalf("unexpected certificate constraints: algorithm=%s is_ca=%v", certificate.SignatureAlgorithm, certificate.IsCA)
	}
	wantUsage := x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment
	if certificate.KeyUsage != wantUsage || len(certificate.ExtKeyUsage) != 1 || certificate.ExtKeyUsage[0] != x509.ExtKeyUsageServerAuth {
		t.Fatalf("unexpected key usage: %v %v", certificate.KeyUsage, certificate.ExtKeyUsage)
	}
	for _, address := range []net.IP{net.ParseIP("127.0.0.1"), net.ParseIP("::1"), net.ParseIP("192.0.2.10")} {
		if !containsIP(certificate.IPAddresses, address) {
			t.Errorf("missing SAN IP %s", address)
		}
	}
}

func containsIP(values []net.IP, wanted net.IP) bool {
	for _, value := range values {
		if value.Equal(wanted) {
			return true
		}
	}
	return false
}
