import json
import os
import tempfile
from datetime import datetime, date, timedelta
from threading import RLock
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.yaml"
STATE_PATH = DATA_DIR / "state.json"

_lock = RLock()

DEFAULT_CONFIG = {
    "version": 1,
    "auth": {
        "pam_service": "login",
        "pam_group": "pam",
    },
    "users": [],
}

DEFAULT_STATE = {
    "version": 1,
    "next_ids": {
        "user": 1,
        "window": 1,
        "grant": 1,
    },
    "usage": {},
    "temporary_grants": [],
    "events": [],
}


def _atomic_write(path: Path, content: str, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _load_yaml():
    if not CONFIG_PATH.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))

    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a YAML object")

    data.setdefault("version", 1)
    data.setdefault("auth", {})
    if not isinstance(data["auth"], dict):
        raise ValueError("config.yaml auth must be an object")
    data["auth"].setdefault("pam_service", "login")
    data["auth"].setdefault("pam_group", "pam")
    data.setdefault("users", [])
    if not isinstance(data["users"], list):
        raise ValueError("config.yaml users must be a list")
    return data


def _load_json():
    if not STATE_PATH.exists():
        return json.loads(json.dumps(DEFAULT_STATE))

    with STATE_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("state.json must contain a JSON object")

    data.setdefault("version", 1)
    data.setdefault("next_ids", {})
    data["next_ids"].setdefault("user", 1)
    data["next_ids"].setdefault("window", 1)
    data["next_ids"].setdefault("grant", 1)
    data.setdefault("usage", {})
    data.setdefault("temporary_grants", [])
    data.setdefault("events", [])
    return data


def _save_yaml(data):
    _atomic_write(
        CONFIG_PATH,
        yaml.safe_dump(
            data,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        ),
    )


def _save_json(data):
    _atomic_write(
        STATE_PATH,
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
    )


def initialize_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with _lock:
        if not CONFIG_PATH.exists():
            _save_yaml(DEFAULT_CONFIG)

        if not STATE_PATH.exists():
            _save_json(DEFAULT_STATE)

        config = _load_yaml()
        state = _load_json()
        _save_yaml(config)
        _save_json(state)


def get_config():
    with _lock:
        return _load_yaml()


def get_pam_service():
    return get_config()["auth"].get("pam_service", "login")


def get_pam_group():
    return get_config()["auth"].get("pam_group", "pam")


def is_admin_allowed(username: str) -> bool:
    """Keep authorization in users.py so PAM group membership is system-backed."""
    from .users import user_in_group
    return user_in_group(username, get_pam_group())


def _find_user(config, user_id):
    for user in config["users"]:
        if int(user["id"]) == int(user_id):
            return user
    return None


def _find_window(config, window_id):
    for user in config["users"]:
        for window in user.get("windows", []):
            if int(window["id"]) == int(window_id):
                return user, window
    return None, None


def list_users():
    with _lock:
        config = _load_yaml()
        return sorted(
            [dict(user) for user in config["users"] if user.get("enabled", True)],
            key=lambda item: item["username"],
        )


def get_user(user_id: int):
    with _lock:
        config = _load_yaml()
        user = _find_user(config, user_id)
        return dict(user) if user else None


def get_user_by_username(username: str):
    with _lock:
        config = _load_yaml()
        for user in config["users"]:
            if user["username"] == username:
                return dict(user)
    return None


def add_user(username: str):
    with _lock:
        config = _load_yaml()
        if any(u["username"] == username for u in config["users"]):
            raise ValueError("User is already configured")

        state = _load_json()
        user_id = int(state["next_ids"]["user"])
        state["next_ids"]["user"] = user_id + 1

        user = {
            "id": user_id,
            "username": username,
            "enabled": True,
            "allowances": {str(day): 0 for day in range(7)},
            "windows": [],
        }
        config["users"].append(user)
        _save_yaml(config)
        _save_json(state)
        return dict(user)


def delete_user(user_id: int):
    with _lock:
        config = _load_yaml()
        user = _find_user(config, user_id)
        if user is None:
            return False

        username = user["username"]
        config["users"] = [
            item for item in config["users"]
            if int(item["id"]) != int(user_id)
        ]

        state = _load_json()
        state["usage"] = {
            key: value
            for key, value in state["usage"].items()
            if not key.startswith(f"{int(user_id)}:")
        }
        state["temporary_grants"] = [
            grant for grant in state["temporary_grants"]
            if int(grant["user_id"]) != int(user_id)
        ]
        state["events"] = [
            event for event in state["events"]
            if event.get("user_id") is None
            or int(event["user_id"]) != int(user_id)
        ]

        _save_yaml(config)
        _save_json(state)
        return username


def set_allowance(user_id: int, weekday: int, seconds: int):
    with _lock:
        config = _load_yaml()
        user = _find_user(config, user_id)
        if user is None:
            raise KeyError("User not found")

        user.setdefault("allowances", {})
        user["allowances"][str(weekday)] = max(0, int(seconds))
        _save_yaml(config)


def add_window(user_id: int, weekday: int, start_minute: int, end_minute: int):
    with _lock:
        config = _load_yaml()
        user = _find_user(config, user_id)
        if user is None:
            raise KeyError("User not found")

        state = _load_json()
        window_id = int(state["next_ids"]["window"])
        state["next_ids"]["window"] = window_id + 1

        user.setdefault("windows", []).append({
            "id": window_id,
            "weekday": int(weekday),
            "start_minute": int(start_minute),
            "end_minute": int(end_minute),
        })

        _save_yaml(config)
        _save_json(state)
        return window_id


def delete_window(window_id: int):
    with _lock:
        config = _load_yaml()
        owner, window = _find_window(config, window_id)
        if owner is None:
            return None

        owner["windows"] = [
            item for item in owner.get("windows", [])
            if int(item["id"]) != int(window_id)
        ]
        _save_yaml(config)
        return int(owner["id"])


def _active_grant_seconds(state, user_id: int, now_iso: str) -> int:
    return sum(
        int(grant["remaining_seconds"])
        for grant in state["temporary_grants"]
        if int(grant["user_id"]) == int(user_id)
        and not grant.get("consumed", False)
        and int(grant.get("remaining_seconds", 0)) > 0
        and (
            grant.get("expires_at") is None
            or grant["expires_at"] > now_iso
        )
    )


def get_user_policy(user_id: int, weekday: int, on_date: date | None = None):
    """Return the complete policy for a specific weekday/date.

    Configuration is always read from the current files, so allowance and
    access-window changes are order-independent.
    """
    with _lock:
        config = _load_yaml()
        user = _find_user(config, user_id)
        if user is None:
            return 0, 0, [], 0

        allowance_seconds = int(
            user.get("allowances", {}).get(str(weekday), 0)
        )
        windows = sorted(
            [
                dict(window)
                for window in user.get("windows", [])
                if int(window["weekday"]) == int(weekday)
            ],
            key=lambda item: int(item["start_minute"]),
        )

        state = _load_json()
        target_date = on_date or datetime.now().date()
        today = target_date.isoformat()
        usage_seconds = int(
            state["usage"].get(f"{int(user_id)}:{today}", 0)
        )

        now = datetime.now().isoformat()
        grant_seconds = _active_grant_seconds(state, user_id, now)

        return allowance_seconds, usage_seconds, windows, grant_seconds


def get_remaining_grant_seconds(user_id: int) -> int:
    with _lock:
        state = _load_json()
        return _active_grant_seconds(
            state,
            user_id,
            datetime.now().isoformat(),
        )


def add_grant(user_id: int, seconds: int):
    with _lock:
        state = _load_json()
        grant_id = int(state["next_ids"]["grant"])
        state["next_ids"]["grant"] = grant_id + 1
        state["temporary_grants"].append({
            "id": grant_id,
            "user_id": int(user_id),
            "seconds": int(seconds),
            "remaining_seconds": int(seconds),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "expires_at": None,
            "consumed": False,
        })
        _save_json(state)
        return grant_id


def consume_grant_seconds(user_id: int, seconds: int):
    if seconds <= 0:
        return

    with _lock:
        state = _load_json()
        now = datetime.now().isoformat()
        remaining = int(seconds)

        for grant in state["temporary_grants"]:
            if remaining <= 0:
                break
            if int(grant["user_id"]) != int(user_id):
                continue
            if grant.get("consumed", False):
                continue
            if int(grant["remaining_seconds"]) <= 0:
                continue
            if (
                grant.get("expires_at") is not None
                and grant["expires_at"] <= now
            ):
                continue

            available = int(grant["remaining_seconds"])
            consumed = min(available, remaining)
            new_remaining = available - consumed
            grant["remaining_seconds"] = new_remaining
            grant["consumed"] = new_remaining <= 0
            remaining -= consumed

        _save_json(state)


def record_usage(user_id: int, seconds: int, usage_date: date | None = None):
    if seconds <= 0:
        return

    with _lock:
        state = _load_json()
        target_date = usage_date or datetime.now().date()
        key = f"{int(user_id)}:{target_date.isoformat()}"
        state["usage"][key] = int(state["usage"].get(key, 0)) + int(seconds)
        _save_json(state)


def get_usage_history(user_id: int, days: int = 14):
    days = max(1, min(int(days), 90))

    with _lock:
        config = _load_yaml()
        state = _load_json()
        user = _find_user(config, user_id)
        if user is None:
            return []

        today = datetime.now().date()
        history = []

        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            weekday = day.weekday()
            allowance = int(
                user.get("allowances", {}).get(str(weekday), 0)
            )
            key = f"{int(user_id)}:{day.isoformat()}"
            used = int(state["usage"].get(key, 0))
            history.append({
                "date": day.isoformat(),
                "weekday": weekday,
                "used_seconds": used,
                "allowance_seconds": allowance,
            })

        return history


def list_grants(user_id: int, limit: int = 20):
    with _lock:
        state = _load_json()
        grants = [
            dict(grant)
            for grant in state["temporary_grants"]
            if int(grant["user_id"]) == int(user_id)
        ]
        grants.sort(key=lambda item: int(item["id"]), reverse=True)
        return grants[:limit]


def record_event(user_id, event_type: str, details: str = ""):
    with _lock:
        state = _load_json()
        state["events"].append({
            "user_id": int(user_id) if user_id is not None else None,
            "event_type": event_type,
            "details": details,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        state["events"] = state["events"][-2000:]
        _save_json(state)
