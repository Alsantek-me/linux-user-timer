import pwd
import subprocess


def linux_user_exists(username: str) -> bool:
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def get_uid(username: str) -> int:
    return pwd.getpwnam(username).pw_uid


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
