import secrets
from pathlib import Path

import pam
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .scheduler import start_scheduler, stop_scheduler
from .storage import (
    initialize_storage,
    get_config,
    get_user,
    list_users,
    get_user_by_username,
    add_user,
    delete_user,
    set_allowance,
    add_window,
    delete_window,
    add_grant,
    list_grants,
    is_admin_allowed,
)
from .users import (
    linux_user_exists,
    lock_user,
    unlock_user,
    terminate_user,
    is_locked,
)


BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_SECRET = __import__("os").environ.get(
    "PARENTAL_CONTROL_SESSION_SECRET"
) or secrets.token_urlsafe(32)

app = FastAPI(
    title="Parental Control",
    version="0.2.0",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="parental_control_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=__import__("os").environ.get(
        "PARENTAL_CONTROL_HTTPS_ONLY", "0"
    ) == "1",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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
    initialize_storage()
    start_scheduler()


@app.on_event("shutdown")
def shutdown():
    stop_scheduler()


def current_user(request: Request):
    username = request.session.get("username")
    if not username:
        return None

    if not is_admin_allowed(username):
        request.session.clear()
        return None

    return username


def require_web_auth(request: Request):
    username = current_user(request)
    if not username:
        next_path = request.url.path
        if request.url.query:
            next_path += f"?{request.url.query}"
        return RedirectResponse(
            f"/login?next={next_path}",
            status_code=303,
        )

    return None


def require_api_auth(request: Request):
    username = current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")
    return username


def check_csrf(request: Request, token: str):
    expected = request.session.get("csrf_token")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def csrf_token(request: Request):
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


class AllowanceRequest(BaseModel):
    weekday: int
    seconds: int


class WindowRequest(BaseModel):
    weekday: int
    start_minute: int
    end_minute: int


class GrantRequest(BaseModel):
    seconds: int


@app.get("/")
def root():
    return {
        "application": "Parental Control",
        "version": "0.2.0",
        "status": "running",
        "authentication": "PAM",
    }


@app.get("/login")
def login_page(request: Request, next: str = "/admin"):
    if current_user(request):
        return RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/admin", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": next if next.startswith("/") else "/admin",
            "error": None,
        },
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/admin"),
):
    username = username.strip()
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/admin"

    try:
        authenticated = pam.pam().authenticate(
            username,
            password,
            service=get_config()["auth"].get("pam_service", "login"),
        )
    except Exception:
        authenticated = False

    if not authenticated:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "next": safe_next,
                "error": "Invalid Linux username or password.",
            },
            status_code=401,
        )

    if not is_admin_allowed(username):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "next": safe_next,
                "error": "This Linux account is not allowed to access the administration panel.",
            },
            status_code=403,
        )

    request.session.clear()
    request.session["username"] = username
    request.session["csrf_token"] = secrets.token_urlsafe(32)

    return RedirectResponse(safe_next, status_code=303)


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    if current_user(request):
        check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/api/users")
def list_users_api(request: Request):
    require_api_auth(request)
    users = list_users()
    return [
        {
            "id": user["id"],
            "username": user["username"],
            "enabled": bool(user.get("enabled", True)),
            "locked": is_locked(user["username"]),
        }
        for user in users
    ]


@app.post("/api/users/{user_id}/lock")
def manually_lock(user_id: int, request: Request):
    require_api_auth(request)
    row = get_user(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    lock_user(row["username"])
    return {"username": row["username"], "locked": True}


@app.post("/api/users/{user_id}/unlock")
def manually_unlock(user_id: int, request: Request):
    require_api_auth(request)
    row = get_user(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    unlock_user(row["username"])
    return {"username": row["username"], "locked": False}


@app.post("/api/users/{user_id}/terminate")
def manually_terminate(user_id: int, request: Request):
    require_api_auth(request)
    row = get_user(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    terminate_user(row["username"])
    return {"username": row["username"], "terminated": True}


@app.post("/api/users/{user_id}/allowance")
def set_allowance_api(user_id: int, request: Request, body: AllowanceRequest):
    require_api_auth(request)
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.weekday not in range(7) or body.seconds < 0:
        raise HTTPException(status_code=400, detail="Invalid allowance")
    set_allowance(user_id, body.weekday, body.seconds)
    return {"user_id": user_id, "weekday": body.weekday, "seconds": body.seconds}


@app.post("/api/users/{user_id}/windows")
def add_window_api(user_id: int, request: Request, body: WindowRequest):
    require_api_auth(request)
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.weekday not in range(7):
        raise HTTPException(status_code=400, detail="Invalid weekday")
    if not (0 <= body.start_minute < 1440):
        raise HTTPException(status_code=400, detail="Invalid start time")
    if not (0 <= body.end_minute <= 1440) or body.end_minute <= body.start_minute:
        raise HTTPException(status_code=400, detail="Invalid end time")
    add_window(user_id, body.weekday, body.start_minute, body.end_minute)
    return {"status": "created"}


@app.delete("/api/windows/{window_id}")
def delete_window_api(window_id: int, request: Request):
    require_api_auth(request)
    user_id = delete_window(window_id)
    if user_id is None:
        raise HTTPException(status_code=404, detail="Window not found")
    return {"status": "deleted"}


@app.post("/api/users/{user_id}/grant")
def grant_time_api(user_id: int, request: Request, body: GrantRequest):
    require_api_auth(request)
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.seconds <= 0:
        raise HTTPException(status_code=400, detail="Grant must be greater than zero")
    add_grant(user_id, body.seconds)
    return {"user_id": user_id, "seconds": body.seconds}


@app.get("/admin")
def admin_page(request: Request):
    redirect = require_web_auth(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "users": list_users(),
            "username": current_user(request),
            "csrf_token": csrf_token(request),
        },
    )


@app.get("/admin/users/{user_id}")
def admin_user_page(request: Request, user_id: int):
    redirect = require_web_auth(request)
    if redirect:
        return redirect

    user = get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    allowances = {
        int(day): int(seconds)
        for day, seconds in user.get("allowances", {}).items()
    }

    windows = sorted(
        [dict(window) for window in user.get("windows", [])],
        key=lambda item: (int(item["weekday"]), int(item["start_minute"])),
    )

    return templates.TemplateResponse(
        request=request,
        name="user.html",
        context={
            "user": user,
            "locked": is_locked(user["username"]),
            "weekdays": WEEKDAYS,
            "allowances": allowances,
            "windows": windows,
            "grants": list_grants(user_id),
            "csrf_token": csrf_token(request),
            "username": current_user(request),
        },
    )


@app.post("/admin/users/{user_id}/allowance")
def admin_set_allowance(
    request: Request,
    user_id: int,
    csrf: str = Form(...),
    weekday: int = Form(...),
    hours: int = Form(...),
    minutes: int = Form(...),
):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if weekday not in range(7) or hours < 0 or minutes < 0 or minutes > 59:
        raise HTTPException(status_code=400, detail="Invalid time")

    set_allowance(user_id, weekday, hours * 3600 + minutes * 60)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/window")
def admin_add_window(
    request: Request,
    user_id: int,
    csrf: str = Form(...),
    weekday: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        start_hour, start_minute = map(int, start_time.split(":"))
        end_hour, end_minute = map(int, end_time.split(":"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format")

    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute

    if weekday not in range(7) or not (0 <= start_total < 1440):
        raise HTTPException(status_code=400, detail="Invalid start time")
    if not (0 <= end_total <= 1440) or end_total <= start_total:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    add_window(user_id, weekday, start_total, end_total)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/windows/{window_id}/delete")
def admin_delete_window(request: Request, window_id: int, csrf: str = Form(...)):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    user_id = delete_window(window_id)
    if user_id is None:
        raise HTTPException(status_code=404, detail="Window not found")

    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/grant")
def admin_grant_time(
    request: Request,
    user_id: int,
    csrf: str = Form(...),
    hours: int = Form(...),
    minutes: int = Form(...),
):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if hours < 0 or minutes < 0 or minutes > 59:
        raise HTTPException(status_code=400, detail="Invalid time")

    seconds = hours * 3600 + minutes * 60
    if seconds <= 0:
        raise HTTPException(status_code=400, detail="Grant must be greater than zero")

    add_grant(user_id, seconds)
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/lock")
def admin_lock_user(request: Request, user_id: int, csrf: str = Form(...)):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    row = get_user(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    lock_user(row["username"])
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/unlock")
def admin_unlock_user(request: Request, user_id: int, csrf: str = Form(...)):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    row = get_user(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    unlock_user(row["username"])
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/terminate")
def admin_terminate_user(request: Request, user_id: int, csrf: str = Form(...)):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    row = get_user(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    terminate_user(row["username"])
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/delete")
def delete_user_admin(request: Request, user_id: int, csrf: str = Form(...)):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    delete_user(user_id)
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/users")
def admin_add_user(
    request: Request,
    csrf: str = Form(...),
    username: str = Form(...),
):
    redirect = require_web_auth(request)
    if redirect:
        return redirect
    check_csrf(request, csrf)

    username = username.strip()
    if not linux_user_exists(username):
        raise HTTPException(status_code=400, detail="Linux user does not exist")

    if get_user_by_username(username) is not None:
        raise HTTPException(status_code=400, detail="User is already configured")

    add_user(username)
    return RedirectResponse("/admin", status_code=303)
