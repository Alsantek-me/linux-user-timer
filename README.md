# Linux Parental Control

A Linux parental-control system for managing Linux user access, daily time allowances, access windows, temporary grants, and automatic session enforcement.

> **Status:** Early development

## Storage

SQLite has been removed.

The application now uses two files under `data/`:

- `config.yaml` — users, daily allowances, access windows, and authentication configuration.
- `state.json` — daily usage, temporary grants, and a bounded event history.

The application never creates or opens `data/parental-control.db`.

`config.yaml` and `state.json` are written atomically and are intended to be root-readable only.

## Web authentication

The administration web interface is protected by **PAM**.

Sign in at:

```text
http://127.0.0.1:8765/admin
```

Use an existing Linux username and its Linux password. The password is passed to PAM for authentication and is not stored by this application.

The PAM service defaults to:

```yaml
auth:
  pam_service: login
```

If your distribution uses a different PAM service, change `pam_service` in `data/config.yaml`.

### Restricting who can use the web panel

By default, any Linux account that successfully authenticates through PAM can access the web panel.

For a restricted administration panel, edit `data/config.yaml`:

```yaml
auth:
  pam_service: login
  admin_users:
    - youradminuser
```

Do **not** add a user controlled by the parental-control enforcement system to `admin_users`, because account locking is performed with `passwd`.

The web session is signed with a randomly generated secret stored in:

```text
/etc/parental-control/session-secret
/etc/parental-control/session-secret.env
```

## Features

- Per-user daily time allowances
- Different allowances for each day of the week
- Multiple access windows per day
- Temporary time grants
- Usage tracking
- Automatic session termination
- Automatic account locking
- Automatic account unlocking
- Reboot-safe enforcement
- PAM-authenticated web administration
- YAML configuration
- JSON runtime state
- systemd service support

## Requirements

The application targets Linux systems using `systemd`.

You need:

- Linux
- Python 3
- `python-venv`
- `pip`
- `systemd`
- PAM
- `sudo`
- `passwd`
- `loginctl`
- Git

The enforcement service requires **root privileges** because it manages other Linux users and their sessions.

## Installation

Clone the repository:

```bash
git clone https://git.shihaam.dev/Alsan/linux-user-timer.git
cd linux-user-timer
```

Make the installer executable:

```bash
chmod +x install.sh
```

Run:

```bash
sudo ./install.sh
```

The installer:

1. Installs Python dependencies including PyYAML and python-pam.
2. Creates the Python virtual environment.
3. Removes the legacy `data/parental-control.db` if it exists.
4. Initializes `config.yaml` and `state.json`.
5. Generates a random web-session secret.
6. Installs and starts the systemd service.

## Service commands

```bash
sudo systemctl status parental-control
sudo systemctl restart parental-control
sudo journalctl -u parental-control -f
```

## Reverse proxy / HTTPS

The application listens on:

```text
127.0.0.1:8765
```

Put it behind your existing Nginx/Apache/reverse proxy if you want remote access.

When HTTPS is provided directly to users, set:

```ini
Environment="PARENTAL_CONTROL_HTTPS_ONLY=1"
```

in the systemd service. This marks the session cookie as HTTPS-only.

## Important security note

This application controls Linux accounts and runs as root. Do not expose port `8765` directly to an untrusted network. Prefer binding it to localhost and placing it behind an HTTPS reverse proxy with appropriate firewall rules.
