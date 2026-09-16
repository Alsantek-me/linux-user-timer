from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: int
    username: str
    enabled: bool


@dataclass
class DailyAllowance:
    user_id: int
    weekday: int
    allowance_seconds: int


@dataclass
class AccessWindow:
    id: int
    user_id: int
    weekday: int
    start_minute: int
    end_minute: int


@dataclass
class TemporaryGrant:
    id: int
    user_id: int
    seconds: int
    expires_at: Optional[str]
    consumed: bool
