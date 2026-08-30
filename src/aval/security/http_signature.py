"""HTTP message signatures (RFC 9421 profile) for agent requests.

The mandate answers *may this purchase happen*. This module answers the question
before it: *is the caller the agent it claims to be*. They are separate on purpose —
an agent that proves its identity still gets nothing the mandate does not allow, and
a request carrying a perfect mandate gets nothing without a valid signature.

Covered components are fixed at `@method`, `@path` and `content-digest`. Letting the
caller choose what its own signature covers is how signed requests get their bodies
swapped: the signature stays valid over the parts nobody cared about.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from collections.abc import Callable, Mapping

from cryptography.hazmat.primitives.asymmetric import ec

from aval.security.content_digest import content_digest_sha256, verify_content_digest_sha256
from aval.security.ecdsa import verify_es256_raw
from aval.security.key_custody import KeyCustodyService

LABEL = "sig1"
REQUIRED_COMPONENTS = ("@method", "@path", "content-digest")
DEFAULT_MAX_AGE_SECONDS = 300


class SignatureError(Exception):
    """Raised with the reason code the edge should answer with."""

    def __init__(self, reason_code: str, human_summary: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.human_summary = human_summary


@dataclass(frozen=True)
class SignatureInput:
    components: tuple[str, ...]
    keyid: str
    created: int
    nonce: str
    raw_params: str


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def build_params(*, keyid: str, created: int, nonce: str) -> str:
    covered = " ".join(f'"{component}"' for component in REQUIRED_COMPONENTS)
    return f'({covered});keyid="{keyid}";created={created};nonce="{nonce}"'


def signature_base(*, method: str, path: str, content_digest: str, raw_params: str) -> bytes:
    """The exact bytes both sides sign.

    The received parameter string is echoed verbatim rather than re-serialised: a
    re-serialisation that normalised anything would verify a message the sender never
    actually signed.
    """
    lines = [
        f'"@method": {method.upper()}',
        f'"@path": {path}',
        f'"content-digest": {content_digest}',
        f'"@signature-params": {raw_params}',
    ]
    return "\n".join(lines).encode("utf-8")


def parse_signature_input(header: str) -> SignatureInput:
    label, _, rest = header.partition("=")
    if label.strip() != LABEL or not rest.startswith("("):
        raise SignatureError("signature_malformed", "Signature-Input malformado.")
    if "," in rest:
        raise SignatureError("signature_malformed", "Apenas uma assinatura é aceita.")
    close = rest.find(")")
    if close < 0:
        raise SignatureError("signature_malformed", "Signature-Input malformado.")
    components = tuple(item.strip().strip('"') for item in rest[1:close].split() if item.strip())
    params: dict[str, str] = {}
    for item in rest[close + 1 :].split(";"):
        if not item.strip():
            continue
        key, _, value = item.partition("=")
        params[key.strip()] = value.strip().strip('"')
    try:
        created = int(params["created"])
    except (KeyError, ValueError) as error:
        raise SignatureError("signature_malformed", "Signature-Input sem created.") from error
    keyid = params.get("keyid", "")
    nonce = params.get("nonce", "")
    if not keyid or not nonce:
        raise SignatureError("signature_malformed", "Signature-Input sem keyid ou nonce.")
    return SignatureInput(
        components=components, keyid=keyid, created=created, nonce=nonce, raw_params=rest
    )


def parse_signature(header: str) -> bytes:
    label, _, rest = header.partition("=")
    rest = rest.strip()
    if label.strip() != LABEL or not rest.startswith(":") or not rest.endswith(":"):
        raise SignatureError("signature_malformed", "Signature malformado.")
    try:
        return base64.b64decode(rest[1:-1], validate=True)
    except (ValueError, TypeError) as error:
        raise SignatureError("signature_malformed", "Signature não é base64.") from error


def sign_request(
    *,
    method: str,
    path: str,
    body: bytes,
    custody: KeyCustodyService,
    kid: str,
    created: int,
    nonce: str | None = None,
) -> dict[str, str]:
    """Produce the three headers an agent sends. Used by the agent and by the tests."""
    digest = content_digest_sha256(body)
    params = build_params(keyid=kid, created=created, nonce=nonce or secrets.token_hex(8))
    base = signature_base(method=method, path=path, content_digest=digest, raw_params=params)
    signature = custody.sign_es256(kid, base)
    return {
        "Content-Digest": digest,
        "Signature-Input": f"{LABEL}={params}",
        "Signature": f"{LABEL}=:{_b64(signature)}:",
    }


def verify_request(
    *,
    method: str,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
    public_key_for: Callable[[str], ec.EllipticCurvePublicKey],
    now_epoch: int,
    seen: "ReplayGuard",
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> SignatureInput:
    signature_input_header = headers.get("signature-input")
    signature_header = headers.get("signature")
    digest_header = headers.get("content-digest")
    if not signature_input_header or not signature_header or not digest_header:
        raise SignatureError("signature_missing", "Requisição de agente não assinada.")

    spec = parse_signature_input(signature_input_header)
    if set(REQUIRED_COMPONENTS) - set(spec.components):
        raise SignatureError(
            "signature_components_insufficient",
            "A assinatura precisa cobrir método, caminho e corpo.",
        )
    if not verify_content_digest_sha256(body, digest_header):
        raise SignatureError("content_digest_mismatch", "O corpo não confere com o digest assinado.")
    if abs(now_epoch - spec.created) > max_age_seconds:
        raise SignatureError("signature_stale", "Assinatura fora da janela de validade.")

    public_key = public_key_for(spec.keyid)
    base = signature_base(
        method=method, path=path, content_digest=digest_header, raw_params=spec.raw_params
    )
    if not verify_es256_raw(public_key, base, parse_signature(signature_header)):
        raise SignatureError("signature_invalid", "Assinatura do agente inválida.")

    # Verified last: an unverified nonce must never be able to burn a real one.
    if not seen.remember(spec.keyid, spec.nonce, now_epoch):
        raise SignatureError("signature_replayed", "Assinatura já utilizada.")
    return spec


class ReplayGuard:
    """Single-process nonce memory.

    Durable double-spend protection lives in the capture idempotency record; this is
    the cheaper layer in front of it that also covers read-shaped requests.
    """

    def __init__(self, *, retain_seconds: int = DEFAULT_MAX_AGE_SECONDS * 2) -> None:
        self._retain_seconds = retain_seconds
        self._seen: dict[tuple[str, str], int] = {}

    def remember(self, keyid: str, nonce: str, now_epoch: int) -> bool:
        self._forget_older_than(now_epoch)
        key = (keyid, nonce)
        if key in self._seen:
            return False
        self._seen[key] = now_epoch
        return True

    def _forget_older_than(self, now_epoch: int) -> None:
        cutoff = now_epoch - self._retain_seconds
        for key in [key for key, seen_at in self._seen.items() if seen_at < cutoff]:
            del self._seen[key]
