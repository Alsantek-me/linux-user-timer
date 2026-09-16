from datetime import datetime
import subprocess

from .database import get_db
from .users import (
    lock_user,
    unlock_user,
    terminate_user,
    is_locked,
)


def user_has_session(username: str) -> bool:
    result = subprocess.run(
        [
            "loginctl",
            "list-users",
            "--no-legend",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        parts = line.split()

        if len(parts) >= 2 and parts[1] == username:
            return True

    return False


def current_time():
    now = datetime.now()
    weekday = now.weekday()
    minute = now.hour * 60 + now.minute

    return now, weekday, minute


def get_user_policy(user_id: int, weekday: int):
    with get_db() as db:
        allowance_row = db.execute(
            """
            SELECT allowance_seconds
            FROM daily_allowances
            WHERE user_id = ?
            AND weekday = ?
            """,
            (
                user_id,
                weekday,
            ),
        ).fetchone()

        allowance_seconds = (
            allowance_row["allowance_seconds"]
            if allowance_row
            else 0
        )

        today = datetime.now().date().isoformat()

        usage_row = db.execute(
            """
            SELECT used_seconds
            FROM usage
            WHERE user_id = ?
            AND date = ?
            """,
            (
                user_id,
                today,
            ),
        ).fetchone()

        usage_seconds = (
            usage_row["used_seconds"]
            if usage_row
            else 0
        )

        windows = db.execute(
            """
            SELECT id, start_minute, end_minute
            FROM access_windows
            WHERE user_id = ?
            AND weekday = ?
            ORDER BY start_minute
            """,
            (
                user_id,
                weekday,
            ),
        ).fetchall()

        grant_row = db.execute(
            """
            SELECT COALESCE(
                SUM(remaining_seconds),
                0
            ) AS total
            FROM temporary_grants
            WHERE user_id = ?
            AND consumed = 0
            AND (
                expires_at IS NULL
                OR expires_at > ?
            )
            """,
            (
                user_id,
                datetime.now().isoformat(),
            ),
        ).fetchone()

        grant_seconds = grant_row["total"]

    return (
        allowance_seconds,
        usage_seconds,
        windows,
        grant_seconds,
    )


def is_inside_window(windows, minute: int) -> bool:
    if not windows:
        return True

    for window in windows:
        if (
            window["start_minute"]
            <= minute
            < window["end_minute"]
        ):
            return True

    return False


def get_remaining_grant_seconds(user_id: int) -> int:
    now = datetime.now().isoformat()

    with get_db() as db:
        row = db.execute(
            """
            SELECT COALESCE(
                SUM(remaining_seconds),
                0
            ) AS total
            FROM temporary_grants
            WHERE user_id = ?
            AND consumed = 0
            AND (
                expires_at IS NULL
                OR expires_at > ?
            )
            """,
            (
                user_id,
                now,
            ),
        ).fetchone()

    return row["total"]


def consume_grant_seconds(
    user_id: int,
    seconds: int,
):
    if seconds <= 0:
        return

    now = datetime.now().isoformat()

    with get_db() as db:
        grants = db.execute(
            """
            SELECT id, remaining_seconds
            FROM temporary_grants
            WHERE user_id = ?
            AND consumed = 0
            AND remaining_seconds > 0
            AND (
                expires_at IS NULL
                OR expires_at > ?
            )
            ORDER BY id ASC
            """,
            (
                user_id,
                now,
            ),
        ).fetchall()

        remaining = seconds

        for grant in grants:
            if remaining <= 0:
                break

            available = grant["remaining_seconds"]

            consumed = min(
                available,
                remaining,
            )

            new_remaining = (
                available - consumed
            )

            db.execute(
                """
                UPDATE temporary_grants
                SET remaining_seconds = ?,
                    consumed = ?
                WHERE id = ?
                """,
                (
                    new_remaining,
                    1 if new_remaining <= 0 else 0,
                    grant["id"],
                ),
            )

            remaining -= consumed


def record_usage(
    user_id: int,
    seconds: int,
):
    if seconds <= 0:
        return

    today = datetime.now().date().isoformat()

    with get_db() as db:
        row = db.execute(
            """
            SELECT used_seconds
            FROM usage
            WHERE user_id = ?
            AND date = ?
            """,
            (
                user_id,
                today,
            ),
        ).fetchone()

        if row is None:
            db.execute(
                """
                INSERT INTO usage (
                    user_id,
                    date,
                    used_seconds
                )
                VALUES (?, ?, ?)
                """,
                (
                    user_id,
                    today,
                    seconds,
                ),
            )
        else:
            db.execute(
                """
                UPDATE usage
                SET used_seconds =
                    used_seconds + ?
                WHERE user_id = ?
                AND date = ?
                """,
                (
                    seconds,
                    user_id,
                    today,
                ),
            )


def record_event(
    user_id: int,
    event_type: str,
    details: str = "",
):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO events (
                user_id,
                event_type,
                details
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                event_type,
                details,
            ),
        )


def evaluate_user(
    user_id: int,
    username: str,
):
    now, weekday, minute = current_time()

    (
        allowance_seconds,
        usage_seconds,
        windows,
        grant_seconds,
    ) = get_user_policy(
        user_id,
        weekday,
    )

    inside_window = is_inside_window(
        windows,
        minute,
    )

    allowance_remaining = max(
        0,
        allowance_seconds - usage_seconds,
    )

    total_remaining = (
        allowance_remaining
        + grant_seconds
    )

    logged_in = user_has_session(
        username
    )

    allowed_by_schedule = (
        inside_window
        and allowance_remaining > 0
    )

    allowed_by_grant = (
        grant_seconds > 0
    )

    should_allow = (
        allowed_by_schedule
        or allowed_by_grant
    )

    locked = is_locked(username)

    if should_allow:
        if locked:
            try:
                unlock_user(username)

                record_event(
                    user_id,
                    "auto_unlock",
                    "Access became available",
                )
            except Exception as exc:
                record_event(
                    user_id,
                    "unlock_error",
                    str(exc),
                )

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
                record_event(
                    user_id,
                    "lock_error",
                    str(exc),
                )

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
    with get_db() as db:
        users = db.execute(
            """
            SELECT id, username, enabled
            FROM users
            WHERE enabled = 1
            ORDER BY id
            """
        ).fetchall()

    results = []

    for user in users:
        try:
            result = evaluate_user(
                user["id"],
                user["username"],
            )

            results.append(result)

        except Exception as exc:
            record_event(
                user["id"],
                "enforcement_error",
                str(exc),
            )

    return results
