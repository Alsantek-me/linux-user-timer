import grp
import pwd
import subprocess
from typing import List, Dict


def linux_user_exists(username: str) -> bool:
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def get_uid(username: str) -> int:
    return pwd.getpwnam(username).pw_uid


def _login_def_value(name: str, default: int) -> int:
    """Read an integer value from /etc/login.defs."""
    try:
        with open("/etc/login.defs", "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == name:
                    value = int(parts[1])
                    if value > 0:
                        return value
    except (OSError, ValueError):
        pass
    return default


def _uid_min() -> int:
    return _login_def_value("UID_MIN", 1000)


def _uid_max() -> int:
    return _login_def_value("UID_MAX", 60000)


def _is_interactive_shell(shell: str) -> bool:
    """Exclude service accounts that cannot be used for interactive logins."""
    shell = (shell or "").strip().lower()
    if not shell:
        return False
    return not shell.endswith(("/nologin", "/false"))


def _supplementary_groups(username: str) -> set[str]:
    groups = set()
    try:
        user = pwd.getpwnam(username)
    except KeyError:
        return groups

    try:
        groups.add(grp.getgrgid(user.pw_gid).gr_name)
    except KeyError:
        pass

    for group in grp.getgrall():
        if username in group.gr_mem:
            groups.add(group.gr_name)

    return groups


def has_root_privileges(username: str) -> bool:
    """Best-effort detection for accounts with ordinary root-style group access."""
    try:
        user = pwd.getpwnam(username)
    except KeyError:
        return False

    if user.pw_uid == 0:
        return True

    groups = _supplementary_groups(username)
    return bool(groups.intersection({"root", "wheel", "sudo"}))


def is_non_root_user(username: str) -> bool:
    """Return True for regular non-root accounts suitable for parental control."""
    try:
        user = pwd.getpwnam(username)
    except KeyError:
        return False

    if user.pw_uid < _uid_min() or user.pw_uid > _uid_max():
        return False

    if username in {"nobody", "nfsnobody"}:
        return False

    if not _is_interactive_shell(user.pw_shell):
        return False

    return not has_root_privileges(username)


def list_available_users() -> List[Dict[str, str]]:
    """Return regular interactive users that can be selected for parental control."""
    users = []

    for user in pwd.getpwall():
        if not is_non_root_user(user.pw_name):
            continue

        users.append({"username": user.pw_name})

    return sorted(users, key=lambda item: item["username"].lower())


def user_in_group(username: str, group_name: str) -> bool:
    try:
        group = grp.getgrnam(group_name)
        user = pwd.getpwnam(username)
    except KeyError:
        return False

    return (
        username in group.gr_mem
        or user.pw_gid == group.gr_gid
    )


def is_locked(username: str) -> bool:
    result = subprocess.run(
        ["passwd", "-S", username],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return False

    parts = result.stdout.split()

    if len(parts) < 2:
        return False

    return parts[1] == "L"


def lock_user(username: str):
    subprocess.run(
        ["loginctl", "terminate-user", username],
        check=False,
    )

    subprocess.run(
        ["passwd", "-l", username],
        check=True,
    )


def unlock_user(username: str):
    subprocess.run(
        ["passwd", "-u", username],
        check=True,
    )


def terminate_user(username: str):
    subprocess.run(
        ["loginctl", "terminate-user", username],
        check=False,
    )
