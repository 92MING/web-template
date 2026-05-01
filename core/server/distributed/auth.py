# -*- coding: utf-8 -*-
"""Inter-node authentication using admin password hash (PBKDF2)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import TypedDict


class AuthChallenge(TypedDict):
    nonce: str
    timestamp: float


class AuthResponse(TypedDict):
    nonce: str
    timestamp: float
    hash: str


def generate_nonce() -> str:
    return secrets.token_hex(16)


def compute_challenge_response(
    nonce: str,
    timestamp: float,
    password_hash_hex: str,
) -> str:
    """Compute HMAC-SHA256 of ``nonce:timestamp`` keyed by the password hash."""
    message = f"{nonce}:{timestamp:.3f}".encode("utf-8")
    key = bytes.fromhex(password_hash_hex)
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_challenge_response(
    nonce: str,
    timestamp: float,
    response_hash: str,
    password_hash_hex: str,
    max_age_seconds: float = 30.0,
) -> bool:
    """Verify a challenge-response, including timestamp freshness."""
    if abs(time.time() - timestamp) > max_age_seconds:
        return False
    expected = compute_challenge_response(nonce, timestamp, password_hash_hex)
    return hmac.compare_digest(expected, response_hash)


def create_auth_challenge() -> AuthChallenge:
    return {"nonce": generate_nonce(), "timestamp": time.time()}


def respond_to_challenge(
    challenge: AuthChallenge,
    password_hash_hex: str,
) -> AuthResponse:
    return {
        "nonce": challenge["nonce"],
        "timestamp": challenge["timestamp"],
        "hash": compute_challenge_response(
            challenge["nonce"], challenge["timestamp"], password_hash_hex
        ),
    }
