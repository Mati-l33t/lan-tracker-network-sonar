import os
import bcrypt
from pathlib import Path
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

_STATIC_DIR  = Path(__file__).parent / "static"
SECRET_KEY   = os.getenv("LT_SECRET_KEY", "changeme")
AUTH_ENABLED = os.getenv("LT_AUTH_ENABLED", "true").lower() == "true"
ADMIN_HASH   = os.getenv("LT_ADMIN_HASH", "")

COOKIE_NAME    = "lt_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

router     = APIRouter()
_serial    = URLSafeTimedSerializer(SECRET_KEY)


def verify_password(plain: str) -> bool:
    if not ADMIN_HASH:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), ADMIN_HASH.encode())
    except Exception:
        return False


def _make_token() -> str:
    return _serial.dumps("authenticated")


def _check_token(token: str) -> bool:
    try:
        _serial.loads(token, max_age=COOKIE_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def is_authenticated(request: Request) -> bool:
    if not AUTH_ENABLED:
        return True
    if not ADMIN_HASH:
        return True
    token = request.cookies.get(COOKIE_NAME)
    return bool(token and _check_token(token))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=302)
    return HTMLResponse((_STATIC_DIR / "login.html").read_text())


@router.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    if verify_password(password):
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(COOKIE_NAME, _make_token(), max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login?error=1", status_code=302)


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp
