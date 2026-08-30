from __future__ import annotations

import base64
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping, Protocol

from aval.domain.entities import AgentIdentity
from aval.security.content_digest import content_digest_sha256, verify_content_digest_sha256
from aval.security.ecdsa import verify_es256_raw
from aval.security.http_signature import ReplayGuard
from aval.security.key_custody import public_key_from_jwk


_REQUIRED_COMPONENTS = (
    "@method",
    "@authority",
    "@path",
    "ucp-agent",
    "idempotency-key",
    "content-digest",
    "content-type",
)
_UCP_AGENT = re.compile(r'^profile="(?P<profile>https://[^"\s]+)"$')
# `created` and `nonce` are mandatory, and both sit inside the signed parameter string,
# so neither can be edited in flight. Without them a signature this lane once emitted
# would authenticate forever: anyone who ever saw one — in a log, a proxy, a capture —
# could replay it unchanged. The agent lane has always required both; this one did not.
_SIGNATURE_INPUT = re.compile(
    r'^sig1=\((?P<components>(?:"(?:@[a-z]+|[a-z-]+)"\s*)+)\)'
    r';keyid="(?P<kid>[^"]+)";alg="(?P<alg>[^"]+)"'
    r';created=(?P<created>\d+);nonce="(?P<nonce>[^"]+)"$'
)
# The window a protocol signature is good for. Matches the agent lane on purpose: one
# system, one answer to "how old is too old".
MAX_AGE_SECONDS = 300
_SIGNATURE = re.compile(r"^sig1=:(?P<signature>[A-Za-z0-9+/]+={0,2}):$")


class TrustedAgentRegistry(Protocol):
    def resolve(self, profile_url: str) -> AgentIdentity | None: ...


class UcpAuthenticationError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class SignedRequest:
    method: str
    authority: str
    path: str
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", {key.lower(): value for key, value in self.headers.items()})

    def with_header(self, name: str, value: str) -> "SignedRequest":
        return replace(self, headers={**self.headers, name.lower(): value})

    def with_content_digest(self) -> "SignedRequest":
        return self.with_header("content-digest", content_digest_sha256(self.body))


def _parse_ucp_agent(value: str | None) -> str:
    match = _UCP_AGENT.fullmatch(value or "")
    if match is None:
        raise UcpAuthenticationError("ucp_agent_invalid")
    return match.group("profile")


def _parse_signature_input(value: str | None) -> tuple[tuple[str, ...], str, int, str]:
    match = _SIGNATURE_INPUT.fullmatch(value or "")
    if match is None or match.group("alg").lower() != "es256":
        raise UcpAuthenticationError("signature_input_invalid")
    components = tuple(re.findall(r'"([^"]+)"', match.group("components")))
    if components != _REQUIRED_COMPONENTS:
        raise UcpAuthenticationError("signature_components_missing")
    return components, match.group("kid"), int(match.group("created")), match.group("nonce")


def _signature_input_value(request: SignedRequest) -> str:
    value = request.headers.get("signature-input")
    if value is None:
        raise UcpAuthenticationError("signature_missing")
    return value


def _component_value(request: SignedRequest, component: str) -> str:
    derived = {
        "@method": request.method.upper(),
        "@authority": request.authority,
        "@path": request.path,
    }
    try:
        return derived[component] if component.startswith("@") else request.headers[component]
    except KeyError as error:
        raise UcpAuthenticationError("signature_components_missing") from error


def signature_base(request: SignedRequest) -> bytes:
    signature_input = _signature_input_value(request)
    components, _, _, _ = _parse_signature_input(signature_input)
    lines = [f'"{component}": {_component_value(request, component)}' for component in components]
    lines.append(f'"@signature-params": {signature_input.partition("=")[2]}')
    return "\n".join(lines).encode("utf-8")


def _parse_signature(value: str | None) -> bytes:
    match = _SIGNATURE.fullmatch(value or "")
    if match is None:
        raise UcpAuthenticationError("signature_missing")
    try:
        signature = base64.b64decode(match.group("signature"), validate=True)
    except ValueError as error:
        raise UcpAuthenticationError("signature_invalid") from error
    if len(signature) != 64:
        raise UcpAuthenticationError("signature_invalid")
    return signature


class Rfc9421Verifier:
    """Authenticate one protocol-lane request.

    `clock` and `seen` are required rather than optional. A replay defence that could be
    left off by forgetting an argument is a replay defence that will eventually be off in
    the deployment that mattered.
    """

    def __init__(
        self,
        registry: TrustedAgentRegistry,
        *,
        clock: Callable[[], datetime],
        seen: ReplayGuard,
        max_age_seconds: int = MAX_AGE_SECONDS,
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._seen = seen
        self._max_age_seconds = max_age_seconds

    def verify(self, request: SignedRequest) -> AgentIdentity:
        profile_url = _parse_ucp_agent(request.headers.get("ucp-agent"))
        identity = self._registry.resolve(profile_url)
        if identity is None or not identity.trusted:
            raise UcpAuthenticationError("profile_not_trusted")
        _, kid, created, nonce = _parse_signature_input(_signature_input_value(request))
        if kid != identity.public_jwk.get("kid"):
            raise UcpAuthenticationError("key_not_found")
        digest = request.headers.get("content-digest")
        if digest is None or not verify_content_digest_sha256(request.body, digest):
            raise UcpAuthenticationError("content_digest_invalid")
        now_epoch = int(self._clock().timestamp())
        if abs(now_epoch - created) > self._max_age_seconds:
            raise UcpAuthenticationError("signature_stale")
        signature = _parse_signature(request.headers.get("signature"))
        try:
            verified = verify_es256_raw(public_key_from_jwk(dict(identity.public_jwk)), signature_base(request), signature)
        except ValueError as error:
            raise UcpAuthenticationError("signature_invalid") from error
        if not verified:
            raise UcpAuthenticationError("signature_invalid")
        # Burned last, after the signature holds. Otherwise anyone could spend another
        # agent's nonces by posting garbage nobody signed.
        if not self._seen.remember(kid, nonce, now_epoch):
            raise UcpAuthenticationError("signature_replayed")
        return identity
