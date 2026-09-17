#!/bin/bash

set -e

# ============================================================
# Linux Parental Control - Installer
# ============================================================

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo:"
    echo "  sudo ./install.sh"
    exit 1
fi

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo
echo "=================================="
echo "Linux Parental Control Installer"
echo "=================================="
echo
echo "Installing from:"
echo "$INSTALL_DIR"
echo


# ============================================================
# Detect Linux distribution
# ============================================================

if [ -f /etc/os-release ]; then
    . /etc/os-release
else
    echo "ERROR: Cannot determine Linux distribution."
    exit 1
fi

echo "Detected:"
echo "  Distribution: ${PRETTY_NAME:-Unknown}"
echo


# ============================================================
# Detect package manager
# ============================================================

PACKAGE_MANAGER=""

if command -v pacman >/dev/null 2>&1; then
    PACKAGE_MANAGER="pacman"

elif command -v apt-get >/dev/null 2>&1; then
    PACKAGE_MANAGER="apt"

elif command -v dnf >/dev/null 2>&1; then
    PACKAGE_MANAGER="dnf"

elif command -v zypper >/dev/null 2>&1; then
    PACKAGE_MANAGER="zypper"

elif command -v apk >/dev/null 2>&1; then
    PACKAGE_MANAGER="apk"

elif command -v xbps-install >/dev/null 2>&1; then
    PACKAGE_MANAGER="xbps"

else
    echo "ERROR: Unsupported Linux distribution."
    echo
    echo "Supported package managers:"
    echo "  pacman"
    echo "  apt"
    echo "  dnf"
    echo "  zypper"
    echo "  apk"
    echo "  xbps"
    exit 1
fi

echo "Package manager:"
echo "  $PACKAGE_MANAGER"
echo


# ============================================================
# Check systemd
# ============================================================

if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemd is required."
    echo
    echo "This installer installs a systemd service."
    exit 1
fi

if [ ! -d /run/systemd/system ]; then
    echo "ERROR: systemd is not currently running."
    echo
    echo "This installer requires a running systemd system."
    exit 1
fi

echo "systemd detected."
echo


# ============================================================
# Install system dependencies
# ============================================================

echo "[1/5] Installing dependencies"

case "$PACKAGE_MANAGER" in

    pacman)
        pacman -Syu --needed --noconfirm \
            python \
            python-pip
        ;;

    apt)
        apt-get update

        DEBIAN_FRONTEND=noninteractive \
        apt-get install -y \
            python3 \
            python3-pip \
            python3-venv
        ;;

    dnf)
        dnf install -y \
            python3 \
            python3-pip
        ;;

    zypper)
        zypper --non-interactive install \
            python3 \
            python3-pip
        ;;

    apk)
        apk add \
            python3 \
            py3-pip \
            py3-virtualenv
        ;;

    xbps)
        xbps-install -Sy \
            python3 \
            python3-pip
        ;;

esac


# ============================================================
# Verify Python
# ============================================================

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 was not installed."
    exit 1
fi

PYTHON="$(command -v python3)"

echo
echo "Python:"
"$PYTHON" --version
echo


# ============================================================
# Create virtual environment
# ============================================================

echo "[2/5] Creating virtual environment"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    "$PYTHON" -m venv "$INSTALL_DIR/.venv"
else
    echo "Virtual environment already exists."
fi


# ============================================================
# Install Python packages
# ============================================================

echo
echo "[3/5] Installing Python packages"

"$INSTALL_DIR/.venv/bin/python" -m pip install \
    --upgrade pip

"$INSTALL_DIR/.venv/bin/python" -m pip install \
    -r "$INSTALL_DIR/requirements.txt"


# ============================================================
# Install systemd service
# ============================================================

echo
echo "[4/5] Installing systemd service"

SERVICE_FILE="/etc/systemd/system/parental-control.service"

sed \
    "s|%INSTALL_DIR%|$INSTALL_DIR|g" \
    "$INSTALL_DIR/parental-control.service" \
    > "$SERVICE_FILE"


# ============================================================
# Enable and start service
# ============================================================

systemctl daemon-reload

systemctl enable parental-control.service

systemctl restart parental-control.service


# ============================================================
# Verify service
# ============================================================

echo
echo "[5/5] Verifying installation"

if systemctl is-active --quiet parental-control.service; then
    SERVICE_STATUS="running"
else
    SERVICE_STATUS="FAILED"
fi


# ============================================================
# Result
# ============================================================

echo
echo "=================================="
echo "Parental Control installed"
echo "=================================="
echo
echo "Distribution:"
echo "  ${PRETTY_NAME:-Unknown}"
echo
echo "Python:"
"$INSTALL_DIR/.venv/bin/python" --version
echo
echo "Installation directory:"
echo "  $INSTALL_DIR"
echo
echo "Service:"
echo "  $SERVICE_STATUS"
echo
echo "Admin panel:"
echo "  http://127.0.0.1:8765/admin"
echo
echo "Service commands:"
echo "  sudo systemctl status parental-control"
echo "  sudo systemctl restart parental-control"
echo "  sudo journalctl -u parental-control -f"
echo
echo "=================================="
