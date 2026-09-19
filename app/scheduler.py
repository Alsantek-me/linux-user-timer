import threading
import time
from datetime import date
from .enforcement import enforce_all_users
from .storage import get_user_policy, record_usage, consume_grant_seconds


CHECK_INTERVAL = 5


class Scheduler:
    def __init__(self, interval: int = CHECK_INTERVAL):
        self.interval = interval
        self._thread = None
        self._stop_event = threading.Event()
        self._last_usage_update = {}

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="parental-control-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 2)

    def _run(self):
        self._tick()
        while not self._stop_event.wait(self.interval):
            self._tick()

    def _tick(self):
        now = time.monotonic()
        results = enforce_all_users()

        for result in results:
            user_id = result["user_id"]
            previous = self._last_usage_update.get(user_id)

            if previous is not None:
                elapsed = max(0, int(now - previous["monotonic"]))
                if elapsed > 0 and previous["allowed"] and previous["logged_in"]:
                    self._record_allowed_usage(
                        user_id,
                        elapsed,
                        previous["weekday"],
                        previous["date"],
                    )

            if result["logged_in"] and result["allowed"]:
                self._last_usage_update[user_id] = {
                    "monotonic": now,
                    "allowed": True,
                    "logged_in": True,
                    "weekday": result["weekday"],
                    "date": result["timestamp"][:10],
                }
            else:
                self._last_usage_update.pop(user_id, None)

    def _record_allowed_usage(self, user_id: int, seconds: int, weekday: int, usage_date: str):
        if seconds <= 0:
            return

        (
            allowance_seconds,
            usage_seconds,
            _windows,
            grant_seconds,
        ) = get_user_policy(user_id, weekday)

        allowance_remaining = max(0, allowance_seconds - usage_seconds)
        normal_usage = min(seconds, allowance_remaining)
        grant_usage = min(max(0, seconds - normal_usage), grant_seconds)
        total_usage = normal_usage + grant_usage

        if total_usage <= 0:
            return

        record_usage(
            user_id,
            total_usage,
            date.fromisoformat(usage_date),
        )

        if grant_usage > 0:
            consume_grant_seconds(user_id, grant_usage)


scheduler = Scheduler()


def start_scheduler():
    scheduler.start()


def stop_scheduler():
    scheduler.stop()
