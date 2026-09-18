from datetime import datetime
import subprocess

from .storage import (
    get_user_policy,
    get_remaining_grant_seconds,
    consume_grant_seconds,
    record_usage,
    record_event,
    list_users,
)
from .users import (
    lock_user,
    unlock_user,
    terminate_user,
    is_locked,
)


def user_has_session(username: str) -> bool:
    result = subprocess.run(
        ["loginctl", "list-users", "--no-legend"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return False

    return any(
        len(parts := line.split()) >= 2 and parts[1] == username
        for line in result.stdout.splitlines()
    )


def current_time():
    now = datetime.now()
    return now, now.weekday(), now.hour * 60 + now.minute


def is_inside_window(windows, minute: int) -> bool:
    if not windows:
        return True

    return any(
        int(window["start_minute"]) <= minute < int(window["end_minute"])
        for window in windows
    )


def evaluate_user(user_id: int, username: str):
    now, weekday, minute = current_time()

    (
        allowance_seconds,
        usage_seconds,
        windows,
        grant_seconds,
    ) = get_user_policy(user_id, weekday)

    inside_window = is_inside_window(windows, minute)
    allowance_remaining = max(0, allowance_seconds - usage_seconds)
    total_remaining = allowance_remaining + grant_seconds
    logged_in = user_has_session(username)

    allowed_by_schedule = inside_window and allowance_remaining > 0
    allowed_by_grant = grant_seconds > 0
    should_allow = allowed_by_schedule or allowed_by_grant

    locked = is_locked(username)

    if should_allow:
        if locked:
            try:
                unlock_user(username)
                record_event(user_id, "auto_unlock", "Access became available")
            except Exception as exc:
                record_event(user_id, "unlock_error", str(exc))
    else:
        if logged_in:
            terminate_user(username)
            record_event(
                user_id,
                "session_terminated",
                "Access is not currently permitted",
            )

        if not locked:
            try:
                lock_user(username)
                record_event(
                    user_id,
                    "auto_lock",
                    "Access is not currently permitted",
                )
            except Exception as exc:
                record_event(user_id, "lock_error", str(exc))

    return {
        "user_id": user_id,
        "username": username,
        "timestamp": now.isoformat(),
        "weekday": weekday,
        "minute": minute,
        "inside_window": inside_window,
        "logged_in": logged_in,
        "allowance_seconds": allowance_seconds,
        "usage_seconds": usage_seconds,
        "allowance_remaining": allowance_remaining,
        "grant_seconds": grant_seconds,
        "total_remaining": total_remaining,
        "allowed": should_allow,
    }


def enforce_all_users():
    users = list_users()
    results = []

    for user in users:
        try:
            results.append(evaluate_user(user["id"], user["username"]))
        except Exception as exc:
            record_event(user["id"], "enforcement_error", str(exc))

    return results
