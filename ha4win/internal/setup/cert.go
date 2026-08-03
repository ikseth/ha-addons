package setup

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/ikseth/ha-addons/ha4win/internal/winapi"
)

type CertificateInfo struct {
	Subject     string
	Fingerprint string
	NotBefore   time.Time
	NotAfter    time.Time
	DNSNames    []string
	IPAddresses []net.IP
}

func EnsureCertificate(certPath, keyPath string, validDays int, extraSANs []string, force bool) (CertificateInfo, bool, error) {
	certExists := regularFile(certPath)
	keyExists := regularFile(keyPath)
	if certExists != keyExists {
		return CertificateInfo{}, false, fmt.Errorf("certificate and key must either both exist or both be absent")
	}
	if certExists && !force {
		info, err := ReadCertificate(certPath)
		return info, false, err
	}
	hostname, err := os.Hostname()
	if err != nil {
		return CertificateInfo{}, false, fmt.Errorf("read hostname: %w", err)
	}
	dnsNames, ipAddresses := discoverSANs(hostname, extraSANs)
	privateKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return CertificateInfo{}, false, fmt.Errorf("generate ECDSA key: %w", err)
	}
	serialLimit := new(big.Int).Lsh(big.NewInt(1), 128)
	serial, err := rand.Int(rand.Reader, serialLimit)
	if err != nil {
		return CertificateInfo{}, false, fmt.Errorf("generate certificate serial: %w", err)
	}
	now := time.Now().UTC()
	template := x509.Certificate{
		SerialNumber:          serial,
		Subject:               pkix.Name{CommonName: hostname},
		Issuer:                pkix.Name{CommonName: hostname},
		NotBefore:             now.Add(-5 * time.Minute),
		NotAfter:              now.Add(time.Duration(validDays) * 24 * time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true,
		IsCA:                  false,
		DNSNames:              dnsNames,
		IPAddresses:           ipAddresses,
	}
	der, err := x509.CreateCertificate(rand.Reader, &template, &template, &privateKey.PublicKey, privateKey)
	if err != nil {
		return CertificateInfo{}, false, fmt.Errorf("create certificate: %w", err)
	}
	keyDER, err := x509.MarshalECPrivateKey(privateKey)
	if err != nil {
		return CertificateInfo{}, false, fmt.Errorf("encode ECDSA key: %w", err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	if err := installCertificatePair(certPath, keyPath, certPEM, keyPEM); err != nil {
		return CertificateInfo{}, false, err
	}
	info, err := ReadCertificate(certPath)
	return info, true, err
}

func ReadCertificate(path string) (CertificateInfo, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return CertificateInfo{}, fmt.Errorf("read certificate: %w", err)
	}
	block, _ := pem.Decode(data)
	if block == nil || block.Type != "CERTIFICATE" {
		return CertificateInfo{}, fmt.Errorf("certificate file does not contain a PEM certificate")
	}
	certificate, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return CertificateInfo{}, fmt.Errorf("parse certificate: %w", err)
	}
	digest := sha256.Sum256(certificate.Raw)
	fingerprintBytes := make([]string, len(digest))
	for index, value := range digest {
		fingerprintBytes[index] = strings.ToUpper(hex.EncodeToString([]byte{value}))
	}
	return CertificateInfo{
		Subject: certificate.Subject.String(), Fingerprint: strings.Join(fingerprintBytes, ":"),
		NotBefore: certificate.NotBefore, NotAfter: certificate.NotAfter,
		DNSNames: append([]string(nil), certificate.DNSNames...), IPAddresses: append([]net.IP(nil), certificate.IPAddresses...),
	}, nil
}

func discoverSANs(hostname string, extra []string) ([]string, []net.IP) {
	dnsSet := map[string]string{}
	ipSet := map[string]net.IP{}
	addDNS := func(value string) {
		value = strings.TrimSpace(value)
		if value != "" {
			dnsSet[strings.ToLower(value)] = value
		}
	}
	addIP := func(value net.IP) {
		if value != nil {
			ipSet[value.String()] = value
		}
	}
	addDNS(hostname)
	if fqdn, err := winapi.Current().FQDN(); err == nil && !strings.EqualFold(fqdn, hostname) {
		addDNS(fqdn)
	}
	interfaces, _ := net.Interfaces()
	for _, networkInterface := range interfaces {
		if networkInterface.Flags&net.FlagUp == 0 || networkInterface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addresses, _ := networkInterface.Addrs()
		for _, address := range addresses {
			ip := interfaceAddressIP(address.String())
			if ip != nil && !ip.IsLoopback() {
				addIP(ip)
			}
		}
	}
	addIP(net.ParseIP("127.0.0.1"))
	addIP(net.ParseIP("::1"))
	for _, value := range extra {
		if ip := net.ParseIP(strings.TrimSpace(value)); ip != nil {
			addIP(ip)
		} else {
			addDNS(value)
		}
	}
	dnsNames := make([]string, 0, len(dnsSet))
	for _, value := range dnsSet {
		dnsNames = append(dnsNames, value)
	}
	sort.Strings(dnsNames)
	ipNames := make([]string, 0, len(ipSet))
	for value := range ipSet {
		ipNames = append(ipNames, value)
	}
	sort.Strings(ipNames)
	ipAddresses := make([]net.IP, 0, len(ipNames))
	for _, value := range ipNames {
		ipAddresses = append(ipAddresses, ipSet[value])
	}
	return dnsNames, ipAddresses
}

func interfaceAddressIP(value string) net.IP {
	if slash := strings.LastIndexByte(value, '/'); slash >= 0 {
		value = value[:slash]
	}
	if zone := strings.LastIndexByte(value, '%'); zone >= 0 {
		value = value[:zone]
	}
	return net.ParseIP(value)
}

func installCertificatePair(certPath, keyPath string, certPEM, keyPEM []byte) error {
	for _, path := range []string{certPath, keyPath} {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			return fmt.Errorf("create certificate directory: %w", err)
		}
	}
	certCandidate := certPath + ".new"
	keyCandidate := keyPath + ".new"
	if err := os.WriteFile(certCandidate, certPEM, 0o600); err != nil {
		return fmt.Errorf("write certificate candidate: %w", err)
	}
	if err := os.WriteFile(keyCandidate, keyPEM, 0o600); err != nil {
		_ = os.Remove(certCandidate)
		return fmt.Errorf("write key candidate: %w", err)
	}
	platform := winapi.Current()
	certBackup := certPath + ".previous"
	keyBackup := keyPath + ".previous"
	hadExistingPair := regularFile(certPath) && regularFile(keyPath)
	if hadExistingPair {
		_ = os.Remove(certBackup)
		_ = os.Remove(keyBackup)
		if err := replacePortable(platform, certPath, certBackup); err != nil {
			return fmt.Errorf("back up certificate: %w", err)
		}
		if err := replacePortable(platform, keyPath, keyBackup); err != nil {
			_ = replacePortable(platform, certBackup, certPath)
			return fmt.Errorf("back up private key: %w", err)
		}
	}
	rollback := func() {
		_ = os.Remove(certPath)
		_ = os.Remove(keyPath)
		if hadExistingPair {
			_ = replacePortable(platform, certBackup, certPath)
			_ = replacePortable(platform, keyBackup, keyPath)
		}
	}
	if err := replacePortable(platform, keyCandidate, keyPath); err != nil {
		_ = os.Remove(certCandidate)
		_ = os.Remove(keyCandidate)
		rollback()
		return fmt.Errorf("promote private key: %w", err)
	}
	if err := replacePortable(platform, certCandidate, certPath); err != nil {
		_ = os.Remove(certCandidate)
		rollback()
		return fmt.Errorf("promote certificate: %w", err)
	}
	_ = os.Remove(certBackup)
	_ = os.Remove(keyBackup)
	return nil
}

func replacePortable(platform winapi.Platform, source, destination string) error {
	if err := platform.ReplaceFile(source, destination); err == nil {
		return nil
	}
	if err := os.Remove(destination); err != nil && !os.IsNotExist(err) {
		return err
	}
	return os.Rename(source, destination)
}

func regularFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}
