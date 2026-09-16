#!/bin/bash

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo"
    exit 1
fi


INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing from:"
echo "$INSTALL_DIR"


echo "[1/5] Installing dependencies"

pacman -S --needed --noconfirm python python-pip


echo "[2/5] Creating virtual environment"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    python -m venv "$INSTALL_DIR/.venv"
fi


echo "[3/5] Installing Python packages"

"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"


echo "[4/5] Installing systemd service"

sed \
"s|%INSTALL_DIR%|$INSTALL_DIR|g" \
"$INSTALL_DIR/parental-control.service" \
> /etc/systemd/system/parental-control.service


systemctl daemon-reload

systemctl enable parental-control.service

systemctl restart parental-control.service


echo
echo "=================================="
echo "Parental Control installed"
echo
echo "Admin panel:"
echo "http://127.0.0.1:8765/admin"
echo
echo "Service status:"
echo "systemctl status parental-control"
echo "=================================="
