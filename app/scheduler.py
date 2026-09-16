import threading
import time
from datetime import datetime

from .enforcement import (
    enforce_all_users,
    record_usage,
    get_user_policy,
    consume_grant_seconds,
)


CHECK_INTERVAL = 5


class Scheduler:

    def __init__(
        self,
        interval: int = CHECK_INTERVAL,
    ):
        self.interval = interval

        self._thread = None
        self._stop_event = threading.Event()

        self._last_usage_update = {}

    def start(self):

        if (
            self._thread is not None
            and self._thread.is_alive()
        ):
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
            self._thread.join(
                timeout=self.interval + 2
            )

    def _run(self):

        # Evaluate immediately when the
        # application starts.
        self._tick()

        while not self._stop_event.wait(
            self.interval
        ):
            self._tick()

    def _tick(self):

        now = time.monotonic()

        results = enforce_all_users()

        for result in results:

            user_id = result["user_id"]

            if not result["logged_in"]:
                self._last_usage_update.pop(
                    user_id,
                    None,
                )
                continue

            if not result["allowed"]:
                self._last_usage_update.pop(
                    user_id,
                    None,
                )
                continue

            previous = (
                self._last_usage_update.get(
                    user_id
                )
            )

            self._last_usage_update[user_id] = now

            if previous is None:
                continue

            elapsed = int(
                now - previous
            )

            if elapsed <= 0:
                continue

            self._record_allowed_usage(
                user_id,
                elapsed,
            )

    def _record_allowed_usage(
        self,
        user_id: int,
        seconds: int,
    ):

        if seconds <= 0:
            return

        weekday = datetime.now().weekday()

        (
            allowance_seconds,
            usage_seconds,
            windows,
            grant_seconds,
        ) = get_user_policy(
            user_id,
            weekday,
        )

        allowance_remaining = max(
            0,
            allowance_seconds
            - usage_seconds,
        )

        normal_usage = min(
            seconds,
            allowance_remaining,
        )

        grant_usage = (
            seconds
            - normal_usage
        )

        if grant_usage > grant_seconds:
            grant_usage = grant_seconds

        total_usage = (
            normal_usage
            + grant_usage
        )

        if total_usage <= 0:
            return

        record_usage(
            user_id,
            total_usage,
        )

        if grant_usage > 0:

            consume_grant_seconds(
                user_id,
                grant_usage,
            )


scheduler = Scheduler()


def start_scheduler():
    scheduler.start()


def stop_scheduler():
    scheduler.stop()
