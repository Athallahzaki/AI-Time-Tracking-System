from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, Optional

from backend.core.database import (
    create_auth_session,
    create_user,
    delete_auth_session,
    get_user_by_session,
    get_user_by_username,
)

import os

PBKDF2_ITERATIONS = 310_000
SESSION_SECONDS = (
    float(
        os.getenv(
            "AUTH_SESSION_HOURS",
            "8",
        )
    )
    * 60
    * 60
)


class AuthenticationError(ValueError):
    pass


class AuthService:
    def hash_password(
        self,
        password: str,
    ) -> str:
        if len(password) < 8:
            raise ValueError(
                "Password must contain at least 8 characters"
            )

        salt = secrets.token_bytes(16)

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
        )

        return (
            f"pbkdf2_sha256"
            f"${PBKDF2_ITERATIONS}"
            f"${salt.hex()}"
            f"${digest.hex()}"
        )

    def verify_password(
        self,
        password: str,
        encoded: str,
    ) -> bool:
        try:
            algorithm, iterations, salt_hex, digest_hex = (
                encoded.split("$", 3)
            )

            if algorithm != "pbkdf2_sha256":
                return False

            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )

            return hmac.compare_digest(
                digest.hex(),
                digest_hex,
            )

        except (ValueError, TypeError):
            return False

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
    ) -> Dict[str, Any]:
        username = username.strip()

        if not username:
            raise ValueError("username is required")

        if role not in {"admin", "viewer"}:
            raise ValueError(
                "role must be admin or viewer"
            )

        if get_user_by_username(username) is not None:
            raise ValueError(
                "username already exists"
            )

        return create_user(
            username=username,
            password_hash=self.hash_password(
                password
            ),
            role=role,
        )

    def login(
        self,
        username: str,
        password: str,
    ) -> Dict[str, Any]:
        user = get_user_by_username(
            username.strip()
        )

        # Same public error for nonexistent/wrong password.
        if (
            user is None
            or not user["enabled"]
            or not self.verify_password(
                password,
                user["password_hash"],
            )
        ):
            raise AuthenticationError(
                "Invalid username or password"
            )

        raw_token = secrets.token_urlsafe(32)

        token_hash = self.hash_token(
            raw_token
        )

        expires_at = (
            time.time()
            + SESSION_SECONDS
        )

        create_auth_session(
            user_id=user["id"],
            token_hash=token_hash,
            expires_at=expires_at,
        )

        return {
            "access_token": raw_token,
            "token_type": "bearer",
            "expires_at": expires_at,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
            },
        }

    def authenticate(
        self,
        raw_token: str,
    ) -> Optional[Dict[str, Any]]:
        return get_user_by_session(
            self.hash_token(raw_token)
        )

    def logout(
        self,
        raw_token: str,
    ) -> None:
        delete_auth_session(
            self.hash_token(raw_token)
        )

    @staticmethod
    def hash_token(
        token: str,
    ) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    def bootstrap_admin(
    self,
    ) -> bool:
        username = os.getenv(
            "INITIAL_ADMIN_USERNAME",
            "admin",
        ).strip()

        password = os.getenv(
            "INITIAL_ADMIN_PASSWORD",
            "",
        )

        if not password:
            return False

        if get_user_by_username(
            username
        ) is not None:
            return False

        self.create_user(
            username=username,
            password=password,
            role="admin",
        )

        return True

auth_service = AuthService()