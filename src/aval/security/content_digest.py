from __future__ import annotations

import base64
import hashlib
import hmac


def content_digest_sha256(raw_body: bytes) -> str:
    digest = base64.b64encode(hashlib.sha256(raw_body).digest()).decode("ascii")
    return f"sha-256=:{digest}:"


def verify_content_digest_sha256(raw_body: bytes, value: str) -> bool:
    return hmac.compare_digest(content_digest_sha256(raw_body), value)
