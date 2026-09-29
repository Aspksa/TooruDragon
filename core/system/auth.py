from __future__ import annotations

import hmac


class AuthService:
    def __init__(self, required: bool, token: str):
        self.required = required
        self.token = token

    def authorize(self, authorization_header: str | None) -> bool:
        if not self.required:
            return True
        if not self.token:
            return False
        if not authorization_header:
            return False

        scheme, _, provided = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not provided:
            return False

        return hmac.compare_digest(provided, self.token)
