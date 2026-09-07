"""Single-admin authentication.

The username and a bcrypt password hash live in the ``settings`` table. On first
boot the password defaults to ``changeme`` and the UI nags until it is changed.

We use the ``bcrypt`` library directly rather than passlib: passlib is unmaintained
and breaks with modern bcrypt releases. bcrypt hashes only the first 72 bytes, so
we hard-truncate to that to avoid a ValueError on long inputs.
"""

from __future__ import annotations

import bcrypt
from sqlalchemy.orm import Session

from .db import get_setting, set_setting

DEFAULT_PASSWORD = "changeme"
_MAX = 72  # bcrypt hashes at most 72 bytes


def _hash(password: str) -> str:
    pw = password.encode("utf-8")[:_MAX]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("ascii")


def _check(password: str, hashed: str) -> bool:
    pw = password.encode("utf-8")[:_MAX]
    try:
        return bcrypt.checkpw(pw, hashed.encode("ascii"))
    except ValueError:
        return False


def _ensure_password(s: Session) -> str:
    h = get_setting(s, "admin_password_hash", "")
    if not h:
        h = _hash(DEFAULT_PASSWORD)
        set_setting(s, "admin_password_hash", h)
    return h


def verify(s: Session, username: str, password: str) -> bool:
    if username != get_setting(s, "admin_username", "admin"):
        return False
    return _check(password, _ensure_password(s))


def set_password(s: Session, new_password: str) -> None:
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    set_setting(s, "admin_password_hash", _hash(new_password))


def uses_default_password(s: Session) -> bool:
    return _check(DEFAULT_PASSWORD, _ensure_password(s))
