from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Form,
)

from fastapi.responses import (
    RedirectResponse,
)

from .scheduler import (
    start_scheduler,
    stop_scheduler,
)

from fastapi.templating import (
    Jinja2Templates,
)

from pydantic import BaseModel


from .database import (
    initialize_database,
    get_db,
)

from .users import (
    linux_user_exists,
    lock_user,
    unlock_user,
    terminate_user,
    is_locked,
)


app = FastAPI(
    title="Parental Control",
    version="0.1.0",
)


templates = Jinja2Templates(
    directory="templates"
)


WEEKDAYS = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


@app.on_event("startup")
def startup():
    initialize_database()
    start_scheduler()


@app.on_event("shutdown")
def shutdown():
    stop_scheduler()


class AllowanceRequest(BaseModel):
    weekday: int
    seconds: int


class WindowRequest(BaseModel):
    weekday: int
    start_minute: int
    end_minute: int


class GrantRequest(BaseModel):
    seconds: int


def get_user(user_id: int):
    with get_db() as db:
        return db.execute(
            """
            SELECT id, username, enabled
            FROM users
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()


@app.get("/")
def root():
    return {
        "application": "Parental Control",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/api/users")
def list_users():
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, username, enabled
            FROM users
            ORDER BY username
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "username": row["username"],
            "enabled": bool(row["enabled"]),
            "locked": is_locked(row["username"])
        }
        for row in rows
    ]


@app.post("/api/users/{user_id}/lock")
def manually_lock(user_id: int):
    row = get_user(user_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    lock_user(row["username"])

    return {
        "username": row["username"],
        "locked": True
    }


@app.post("/api/users/{user_id}/unlock")
def manually_unlock(user_id: int):
    row = get_user(user_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    unlock_user(row["username"])

    return {
        "username": row["username"],
        "locked": False
    }


@app.post("/api/users/{user_id}/terminate")
def manually_terminate(user_id: int):
    row = get_user(user_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    terminate_user(row["username"])

    return {
        "username": row["username"],
        "terminated": True
    }


@app.post("/api/users/{user_id}/allowance")
def set_allowance(
    user_id: int,
    request: AllowanceRequest
):
    if get_user(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if request.weekday < 0 or request.weekday > 6:
        raise HTTPException(
            status_code=400,
            detail="Invalid weekday"
        )

    if request.seconds < 0:
        raise HTTPException(
            status_code=400,
            detail="Allowance cannot be negative"
        )

    with get_db() as db:
        db.execute(
            """
            INSERT INTO daily_allowances
            (
                user_id,
                weekday,
                allowance_seconds
            )
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, weekday)
            DO UPDATE SET
                allowance_seconds = excluded.allowance_seconds
            """,
            (
                user_id,
                request.weekday,
                request.seconds
            )
        )

    return {
        "user_id": user_id,
        "weekday": request.weekday,
        "seconds": request.seconds
    }


@app.post("/api/users/{user_id}/windows")
def add_window(
    user_id: int,
    request: WindowRequest
):
    if get_user(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if request.weekday < 0 or request.weekday > 6:
        raise HTTPException(
            status_code=400,
            detail="Invalid weekday"
        )

    if request.start_minute < 0 or request.start_minute >= 1440:
        raise HTTPException(
            status_code=400,
            detail="Invalid start time"
        )

    if request.end_minute < 0 or request.end_minute > 1440:
        raise HTTPException(
            status_code=400,
            detail="Invalid end time"
        )

    if request.end_minute <= request.start_minute:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )

    with get_db() as db:
        db.execute(
            """
            INSERT INTO access_windows
            (
                user_id,
                weekday,
                start_minute,
                end_minute
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                request.weekday,
                request.start_minute,
                request.end_minute
            )
        )

    return {
        "status": "created"
    }


@app.delete("/api/windows/{window_id}")
def delete_window(window_id: int):
    with get_db() as db:
        cursor = db.execute(
            """
            DELETE FROM access_windows
            WHERE id = ?
            """,
            (window_id,)
        )

    if cursor.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail="Window not found"
        )

    return {
        "status": "deleted"
    }


@app.post("/api/users/{user_id}/grant")
def grant_time(
    user_id: int,
    request: GrantRequest
):
    if get_user(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if request.seconds <= 0:
        raise HTTPException(
            status_code=400,
            detail="Grant must be greater than zero"
        )

    with get_db() as db:
       db.execute(
          """
          INSERT INTO temporary_grants
          (
              user_id,
              seconds,
              remaining_seconds
          )
          VALUES (?, ?, ?)
          """,
          (
              user_id,
              request.seconds,
              request.seconds
          )
       )
    return {
        "user_id": user_id,
        "seconds": request.seconds
    }


@app.get("/admin")
def admin_page(
    request: Request
):
    with get_db() as db:
        users = db.execute(
            """
            SELECT id, username, enabled
            FROM users
            ORDER BY username
            """
        ).fetchall()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "users": users
        }
    )


@app.get("/admin/users/{user_id}")
def admin_user_page(
    request: Request,
    user_id: int
):
    user = get_user(user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    with get_db() as db:

        allowances = db.execute(
            """
            SELECT weekday, allowance_seconds
            FROM daily_allowances
            WHERE user_id = ?
            ORDER BY weekday
            """,
            (user_id,)
        ).fetchall()

        windows = db.execute(
            """
            SELECT
                id,
                weekday,
                start_minute,
                end_minute
            FROM access_windows
            WHERE user_id = ?
            ORDER BY weekday, start_minute
            """,
            (user_id,)
        ).fetchall()

        grants = db.execute(
            """
            SELECT
                id,
                seconds,
                created_at,
                expires_at,
                consumed
            FROM temporary_grants
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (user_id,)
        ).fetchall()

    allowance_map = {
        row["weekday"]: row["allowance_seconds"]
        for row in allowances
    }

    return templates.TemplateResponse(
        request=request,
        name="user.html",
        context={
            "user": user,
            "locked": is_locked(user["username"]),
            "weekdays": WEEKDAYS,
            "allowances": allowance_map,
            "windows": windows,
            "grants": grants,
        }
    )


@app.post("/admin/users/{user_id}/allowance")
def admin_set_allowance(
    user_id: int,
    weekday: int = Form(...),
    hours: int = Form(...),
    minutes: int = Form(...),
):
    if get_user(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if weekday < 0 or weekday > 6:
        raise HTTPException(
            status_code=400,
            detail="Invalid weekday"
        )

    if hours < 0 or minutes < 0 or minutes > 59:
        raise HTTPException(
            status_code=400,
            detail="Invalid time"
        )

    seconds = (hours * 3600) + (minutes * 60)

    with get_db() as db:
        db.execute(
            """
            INSERT INTO daily_allowances
            (
                user_id,
                weekday,
                allowance_seconds
            )
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, weekday)
            DO UPDATE SET
                allowance_seconds = excluded.allowance_seconds
            """,
            (
                user_id,
                weekday,
                seconds
            )
        )

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/window")
def admin_add_window(
    user_id: int,
    weekday: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
):
    if get_user(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    try:
        start_hour, start_minute = map(
            int,
            start_time.split(":")
        )

        end_hour, end_minute = map(
            int,
            end_time.split(":")
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid time format"
        )

    start_total = (
        start_hour * 60
        + start_minute
    )

    end_total = (
        end_hour * 60
        + end_minute
    )

    if weekday < 0 or weekday > 6:
        raise HTTPException(
            status_code=400,
            detail="Invalid weekday"
        )

    if start_total < 0 or start_total >= 1440:
        raise HTTPException(
            status_code=400,
            detail="Invalid start time"
        )

    if end_total <= start_total:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )

    with get_db() as db:
        db.execute(
            """
            INSERT INTO access_windows
            (
                user_id,
                weekday,
                start_minute,
                end_minute
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                weekday,
                start_total,
                end_total
            )
        )

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=303
    )


@app.post("/admin/windows/{window_id}/delete")
def admin_delete_window(
    window_id: int
):
    with get_db() as db:
        row = db.execute(
            """
            SELECT user_id
            FROM access_windows
            WHERE id = ?
            """,
            (window_id,)
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Window not found"
            )

        user_id = row["user_id"]

        db.execute(
            """
            DELETE FROM access_windows
            WHERE id = ?
            """,
            (window_id,)
        )

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/grant")
def admin_grant_time(
    user_id: int,
    hours: int = Form(...),
    minutes: int = Form(...),
):
    if get_user(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if hours < 0 or minutes < 0 or minutes > 59:
        raise HTTPException(
            status_code=400,
            detail="Invalid time"
        )

    seconds = (
        hours * 3600
        + minutes * 60
    )

    if seconds <= 0:
        raise HTTPException(
            status_code=400,
            detail="Grant must be greater than zero"
        )

    with get_db() as db:
        db.execute(
           """
           INSERT INTO temporary_grants
           (
               user_id,
               seconds,
               remaining_seconds
           )
           VALUES (?, ?, ?)
           """,
           (
               user_id,
               seconds,
               seconds
            )
        )

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/lock")
def admin_lock_user(
    user_id: int
):
    row = get_user(user_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    lock_user(row["username"])

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/unlock")
def admin_unlock_user(
    user_id: int
):
    row = get_user(user_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    unlock_user(row["username"])

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/terminate")
def admin_terminate_user(
    user_id: int
):
    row = get_user(user_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    terminate_user(row["username"])

    return RedirectResponse(
        f"/admin/users/{user_id}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/delete")
def delete_user(
    user_id: int
):
    with get_db() as db:
        db.execute(
            """
            DELETE FROM users
            WHERE id = ?
            """,
            (user_id,)
        )

    return RedirectResponse(
        "/admin",
        status_code=303
    )


@app.post("/admin/users")
def admin_add_user(
    username: str = Form(...)
):
    username = username.strip()

    if not linux_user_exists(username):
        raise HTTPException(
            status_code=400,
            detail="Linux user does not exist"
        )

    with get_db() as db:

        existing = db.execute(
            """
            SELECT id
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if existing is not None:
            raise HTTPException(
                status_code=400,
                detail="User is already configured"
            )

        cursor = db.execute(
            """
            INSERT INTO users(username)
            VALUES(?)
            """,
            (username,)
        )

        user_id = cursor.lastrowid

        for weekday in range(7):
            db.execute(
                """
                INSERT INTO daily_allowances
                (
                    user_id,
                    weekday,
                    allowance_seconds
                )
                VALUES (?, ?, ?)
                """,
                (
                    user_id,
                    weekday,
                    0
                )
            )

    return RedirectResponse(
        "/admin",
        status_code=303
    )
