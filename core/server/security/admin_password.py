# -*- coding: utf-8 -*-
"""Runtime-only admin password hashing state.

Main process behavior:
    - reads ADMIN_PW when present
    - otherwise generates a temporary password for this startup
    - hashes it with PBKDF2-HMAC-SHA256 and keeps only the hash state

Worker behavior:
    - restores the hash state from env-only hash metadata
    - never requires access to plaintext
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets

from dataclasses import dataclass


_logger = logging.getLogger(__name__)

ADMIN_PASSWORD_HASH_ENV = "__ADMIN_PW_HASH__"
ADMIN_PASSWORD_SALT_ENV = "__ADMIN_PW_SALT__"
ADMIN_PASSWORD_ITER_ENV = "__ADMIN_PW_ITER__"
ADMIN_PASSWORD_SOURCE_ENV = "__ADMIN_PW_SOURCE__"

DEFAULT_ADMIN_PASSWORD_ITERATIONS = 390000


@dataclass(frozen=True, slots=True)
class AdminPasswordState:
    hash_b64: str
    salt_b64: str
    iterations: int
    source: str


_ADMIN_PASSWORD_STATE: AdminPasswordState | None = None


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.b64decode(str(raw or "").encode("ascii"))


def _hash_password(password: str, salt: bytes, *, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt,
        int(iterations),
    )


def _clear_plaintext_password_env() -> None:
    os.environ.pop("ADMIN_PW", None)


def _install_state(*, hash_bytes: bytes, salt: bytes, iterations: int, source: str) -> AdminPasswordState:
    global _ADMIN_PASSWORD_STATE
    state = AdminPasswordState(
        hash_b64=_b64encode(hash_bytes),
        salt_b64=_b64encode(salt),
        iterations=int(iterations),
        source=str(source or "unknown"),
    )
    _ADMIN_PASSWORD_STATE = state
    os.environ[ADMIN_PASSWORD_HASH_ENV] = state.hash_b64
    os.environ[ADMIN_PASSWORD_SALT_ENV] = state.salt_b64
    os.environ[ADMIN_PASSWORD_ITER_ENV] = str(state.iterations)
    os.environ[ADMIN_PASSWORD_SOURCE_ENV] = state.source
    return state


def clear_admin_password_state(*, clear_env: bool = True) -> None:
    global _ADMIN_PASSWORD_STATE
    _ADMIN_PASSWORD_STATE = None
    if not clear_env:
        return
    os.environ.pop(ADMIN_PASSWORD_HASH_ENV, None)
    os.environ.pop(ADMIN_PASSWORD_SALT_ENV, None)
    os.environ.pop(ADMIN_PASSWORD_ITER_ENV, None)
    os.environ.pop(ADMIN_PASSWORD_SOURCE_ENV, None)


def load_admin_password_state_from_env() -> AdminPasswordState | None:
    global _ADMIN_PASSWORD_STATE
    hash_b64 = os.environ.get(ADMIN_PASSWORD_HASH_ENV)
    salt_b64 = os.environ.get(ADMIN_PASSWORD_SALT_ENV)
    iter_text = os.environ.get(ADMIN_PASSWORD_ITER_ENV)
    source = os.environ.get(ADMIN_PASSWORD_SOURCE_ENV, "env-hash")
    if not hash_b64 or not salt_b64 or not iter_text:
        return None
    try:
        iterations = int(iter_text)
        _b64decode(hash_b64)
        _b64decode(salt_b64)
    except Exception:
        _logger.warning("Invalid admin password hash env detected; ignoring runtime admin auth state.")
        return None
    _ADMIN_PASSWORD_STATE = AdminPasswordState(
        hash_b64=hash_b64,
        salt_b64=salt_b64,
        iterations=iterations,
        source=str(source or "env-hash"),
    )
    return _ADMIN_PASSWORD_STATE


def get_admin_password_state() -> AdminPasswordState | None:
    if _ADMIN_PASSWORD_STATE is not None:
        return _ADMIN_PASSWORD_STATE
    return load_admin_password_state_from_env()


def has_admin_password() -> bool:
    return get_admin_password_state() is not None


def verify_admin_password(password: str) -> bool:
    state = get_admin_password_state()
    if state is None:
        return False
    actual = _hash_password(password, _b64decode(state.salt_b64), iterations=state.iterations)
    return hmac.compare_digest(actual, _b64decode(state.hash_b64))


def initialize_admin_password(*, logger: logging.Logger, allow_generate: bool = False) -> str | None:
    raw_password = os.environ.get("ADMIN_PW")
    source = "ADMIN_PW"

    generated_password: str | None = None
    if not raw_password:
        if not allow_generate:
            load_admin_password_state_from_env()
            return None
        raw_password = secrets.token_urlsafe(18)
        generated_password = raw_password
        source = "generated"

    salt = secrets.token_bytes(16)
    hash_bytes = _hash_password(raw_password, salt, iterations=DEFAULT_ADMIN_PASSWORD_ITERATIONS)
    _install_state(
        hash_bytes=hash_bytes,
        salt=salt,
        iterations=DEFAULT_ADMIN_PASSWORD_ITERATIONS,
        source=source,
    )
    _clear_plaintext_password_env()

    if generated_password is not None:
        logger.warning(
            "ADMIN_PW not set; generated temporary admin password for this startup: %s",
            generated_password,
        )
        return generated_password

    logger.info("Admin password loaded from %s and hashed into runtime memory.", source)
    return None


__all__ = [
    "ADMIN_PASSWORD_HASH_ENV",
    "ADMIN_PASSWORD_SALT_ENV",
    "ADMIN_PASSWORD_ITER_ENV",
    "ADMIN_PASSWORD_SOURCE_ENV",
    "AdminPasswordState",
    "clear_admin_password_state",
    "get_admin_password_state",
    "has_admin_password",
    "initialize_admin_password",
    "load_admin_password_state_from_env",
    "verify_admin_password",
]