# Linux Parental Control

A Linux parental-control system for managing Linux user access, daily time allowances, access windows, temporary grants, and automatic session enforcement.

> **Status:** Early development

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
- Web-based administration
- SQLite database
- systemd service support

---

# Requirements

The application currently targets Linux systems using `systemd`.

You need:

- Linux
- Python 3
- `python-venv`
- `pip`
- `systemd`
- `sudo`
- `passwd`
- `loginctl`
- Git

The enforcement service requires **root privileges** because it manages other Linux users and their sessions.

---

# 1. Clone the Repository

Clone the repository:

```bash
git clone https://github.com/Alsantek-me/linux-user-timer.git
```

## 2. Make it executable
```bash
chmod +x install.sh
```

## 3. Run the install script
```bash
sudo ./install.sh
```
### You can access it via http://127.0.0.1:8765/admin 


