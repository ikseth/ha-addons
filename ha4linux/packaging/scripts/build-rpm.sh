#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HA4LINUX_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
VERSION="${1:-$(jq -r '.version' "${HA4LINUX_ROOT}/config.json")}" 
RELEASE="${2:-1}"
TOPDIR="$(mktemp -d)"
SRCROOT="${TOPDIR}/ha4linux-client-${VERSION}"

mkdir -p "${TOPDIR}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
mkdir -p "${SRCROOT}"

cp -a "${HA4LINUX_ROOT}/app" "${SRCROOT}/"
cp -a "${HA4LINUX_ROOT}/requirements.txt" "${SRCROOT}/"
mkdir -p "${SRCROOT}/packaging/common" "${SRCROOT}/packaging/assets"
cp -a "${HA4LINUX_ROOT}/packaging/common/install-client.sh" "${SRCROOT}/packaging/common/"
cp -a "${HA4LINUX_ROOT}/packaging/common/uninstall-client.sh" "${SRCROOT}/packaging/common/"
cp -a "${HA4LINUX_ROOT}/packaging/assets/." "${SRCROOT}/packaging/assets/"

TARBALL="${TOPDIR}/SOURCES/ha4linux-client-${VERSION}.tar.gz"
tar -C "${TOPDIR}" -czf "${TARBALL}" "ha4linux-client-${VERSION}"

cat > "${TOPDIR}/SPECS/ha4linux-client.spec" << EOF_SPEC
Name:           ha4linux-client
Version:        ${VERSION}
Release:        ${RELEASE}%{?dist}
Summary:        HA4Linux client API installer and service
License:        MIT
BuildArch:      noarch
Requires:       python3, python3-pip, sudo, openssl, ca-certificates, systemd
Source0:        ha4linux-client-${VERSION}.tar.gz

%description
Installs HA4Linux API as a systemd service with dedicated user, TLS and sudoers policy.

%prep
%setup -q

%build

%install
mkdir -p %{buildroot}/usr/lib/ha4linux
mkdir -p %{buildroot}/usr/sbin
cp -a app %{buildroot}/usr/lib/ha4linux/
cp -a requirements.txt %{buildroot}/usr/lib/ha4linux/
cp -a packaging/assets %{buildroot}/usr/lib/ha4linux/
cp -a packaging/common/install-client.sh %{buildroot}/usr/lib/ha4linux/
cp -a packaging/common/uninstall-client.sh %{buildroot}/usr/lib/ha4linux/

cat > %{buildroot}/usr/sbin/ha4linux-install-client << 'EOSH'
#!/usr/bin/env bash
exec /usr/lib/ha4linux/install-client.sh "$@"
EOSH
chmod 755 %{buildroot}/usr/sbin/ha4linux-install-client

cat > %{buildroot}/usr/sbin/ha4linux-uninstall-client << 'EOSH'
#!/usr/bin/env bash
exec /usr/lib/ha4linux/uninstall-client.sh "$@"
EOSH
chmod 755 %{buildroot}/usr/sbin/ha4linux-uninstall-client

%post
/usr/lib/ha4linux/install-client.sh --skip-deps || true

%preun
if [ \$1 -eq 0 ]; then
  /usr/lib/ha4linux/uninstall-client.sh || true
fi

%files
/usr/lib/ha4linux
/usr/sbin/ha4linux-install-client
/usr/sbin/ha4linux-uninstall-client

%changelog
* Tue Feb 24 2026 HA4Linux <noreply@example.com> - ${VERSION}-${RELEASE}
- Initial package
EOF_SPEC

rpmbuild --define "_topdir ${TOPDIR}" -bb "${TOPDIR}/SPECS/ha4linux-client.spec"
find "${TOPDIR}/RPMS" -type f -name '*.rpm' -exec cp -v {} "${HA4LINUX_ROOT}/packaging/" \;

echo "RPM package copied to ${HA4LINUX_ROOT}/packaging"
rm -rf "${TOPDIR}"
