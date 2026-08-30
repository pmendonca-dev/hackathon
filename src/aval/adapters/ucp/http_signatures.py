from __future__ import annotations

import base64
import re
from dataclasses import dataclass, replace
from typing import Mapping, Protocol

from aval.domain.entities import AgentIdentity
from aval.security.content_digest import content_digest_sha256, verify_content_digest_sha256
from aval.security.ecdsa import verify_es256_raw
from aval.security.key_custody import public_key_from_jwk


_BASE_REQUIRED_COMPONENTS = (
    "@method",
    "@authority",
    "@path",
    "ucp-agent",
    "content-digest",
    "content-type",
)
_UCP_AGENT = re.compile(r'^profile="(?P<profile>https://[^"\s]+)"$')
_SIGNATURE_INPUT = re.compile(
    r'^sig1=\((?P<components>(?:"(?:@[a-z]+|[a-z-]+)"\s*)+)\)'
    r';keyid="(?P<kid>[^"]+)";alg="(?P<alg>[^"]+)"$'
)
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


def _accepted_components(request: SignedRequest) -> tuple[tuple[str, ...], ...]:
    post_components = (
        "@method", "@authority", "@path", "ucp-agent", "idempotency-key",
        "content-digest", "content-type",
    )
    if request.method.upper() == "POST":
        return (post_components,)
    # Readers do not require an idempotency key, but accept an older signed
    # client that supplies one as an additional covered component.
    return (_BASE_REQUIRED_COMPONENTS, post_components)


def _parse_signature_input(
    value: str | None, *, accepted_components: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], str]:
    match = _SIGNATURE_INPUT.fullmatch(value or "")
    if match is None or match.group("alg").lower() != "es256":
        raise UcpAuthenticationError("signature_input_invalid")
    components = tuple(re.findall(r'"([^"]+)"', match.group("components")))
    if components not in accepted_components:
        raise UcpAuthenticationError("signature_components_missing")
    return components, match.group("kid")


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
    components, _ = _parse_signature_input(signature_input, accepted_components=_accepted_components(request))
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
    def __init__(self, registry: TrustedAgentRegistry) -> None:
        self._registry = registry

    def verify(self, request: SignedRequest) -> AgentIdentity:
        profile_url = _parse_ucp_agent(request.headers.get("ucp-agent"))
        identity = self._registry.resolve(profile_url)
        if identity is None or not identity.trusted:
            raise UcpAuthenticationError("profile_not_trusted")
        _, kid = _parse_signature_input(
            _signature_input_value(request), accepted_components=_accepted_components(request)
        )
        if kid != identity.public_jwk.get("kid"):
            raise UcpAuthenticationError("key_not_found")
        digest = request.headers.get("content-digest")
        if digest is None or not verify_content_digest_sha256(request.body, digest):
            raise UcpAuthenticationError("content_digest_invalid")
        signature = _parse_signature(request.headers.get("signature"))
        try:
            verified = verify_es256_raw(public_key_from_jwk(dict(identity.public_jwk)), signature_base(request), signature)
        except ValueError as error:
            raise UcpAuthenticationError("signature_invalid") from error
        if not verified:
            raise UcpAuthenticationError("signature_invalid")
        return identity
