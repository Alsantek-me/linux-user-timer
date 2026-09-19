# Linux Parental Control

A Linux parental-control system for managing Linux user access, daily time allowances, access windows, temporary grants, usage history, and automatic session enforcement.

## Storage

SQLite has been removed.

The application uses two files under `data/`:

- `config.yaml` — users, daily allowances, access windows, and PAM configuration.
- `state.json` — daily usage, temporary grants, event history, and ID counters.

The application never creates or opens `data/parental-control.db`.

## Web authentication

The administration web interface uses Linux PAM for password authentication and a Linux group for authorization.

The default PAM settings are:

```yaml
auth:
  pam_service: login
  pam_group: pam
```

The installer creates the `pam` group and adds `root` to it. Any Linux account that successfully authenticates through the configured PAM service must also belong to this group to access `/admin`.

To grant another administrator access:

```bash
sudo usermod -aG pam username
```

To remove access:

```bash
sudo gpasswd -d username pam
```

The application re-checks group membership on each request, so a removed member cannot continue using an existing session.

## Adding parental-control users

The web interface provides a drop-down containing eligible regular Linux accounts that are not already configured.

The selector excludes:

- `root` / UID 0 accounts.
- System accounts below the configured `UID_MIN`.
- Accounts in the standard `wheel`, `sudo`, or `root` groups.

This is intended to prevent the administrator account from accidentally being selected for parental enforcement.

## Policy behavior

Daily allowance and access windows are independent configuration items and may be created in any order.

For a normal daily allowance:

- If a day has no access window, there is no time-of-day restriction for that day.
- If a day has one or more access windows, normal allowance access is permitted only while the current time is inside at least one configured window.
- The daily allowance still limits the total normal usage for that day.
- A temporary grant overrides the normal allowance and access-window restriction.

The scheduler re-reads the current YAML/JSON state every enforcement cycle, so changing an allowance before or after a window produces the same final policy.

## Usage graph

Each managed user has a 14-day usage view showing:

- Total usage over the last 14 calendar days.
- Usage today.
- Remaining allowance today.
- A daily graph comparing recorded usage with the configured daily allowance.

Usage data is stored in `state.json` and survives service restarts.

## Requirements

The application targets Linux systems using `systemd`.

You need Linux, Python 3, Python virtual-environment support, pip, systemd, PAM, `sudo`, `passwd`, `loginctl`, and the standard user/group management commands.

The enforcement service runs as `root` because it manages other Linux users and their sessions.

## Installation

```bash
git clone https://git.shihaam.dev/Alsan/linux-user-timer.git
cd linux-user-timer
chmod +x install.sh
sudo ./install.sh
```

The Arch Linux installer intentionally runs:

```bash
pacman -S --needed python python-pip
```

It does **not** run `pacman -Syu`, so installing this application does not trigger a full Arch system upgrade.

The installer also creates the `pam` group, adds `root`, creates the Python virtual environment, installs the application dependencies, removes the old SQLite database if present, creates the systemd service, and starts it.

## Service commands

```bash
sudo systemctl status parental-control
sudo systemctl restart parental-control
sudo journalctl -u parental-control -f
```

The administration panel is available at:

```text
http://127.0.0.1:8765/admin
```

## Reverse proxy / HTTPS

The application listens on:

```text
127.0.0.1:8765
```

Put it behind your existing Nginx/Apache/reverse proxy if remote access is required.

For HTTPS-only session cookies, set this in the systemd service:

```ini
Environment="PARENTAL_CONTROL_HTTPS_ONLY=1"
```

## Security note

This application controls Linux accounts and runs as root. Do not expose port `8765` directly to an untrusted network. Prefer localhost binding with an HTTPS reverse proxy and appropriate firewall rules.
