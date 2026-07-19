"""Endpoint egress policy: allowlist, DNS resolution, and address pinning.

`HTTPSpec.endpoint` is partner-supplied and handed to `httpx`. Without this
module a hosted worker is an SSRF primitive: a partner points a target at
`169.254.169.254` and the worker fetches cloud credentials from its own network
position.

Two properties do the work, and neither is sufficient alone:

1. **Every resolved address is checked, not just the string.** A hostname the
   partner controls can resolve to `127.0.0.1`, so validating the URL text
   catches nothing. Every A and AAAA record must be publicly routable.
2. **The connection is pinned to a validated address.** A preflight
   `getaddrinfo()` followed by an ordinary request is still rebindable: the
   resolver can answer public during validation and private microseconds later
   when the client resolves it again. `ValidatedEndpoint.pinned_url` is dialled
   instead, with the original hostname retained for TLS/SNI and `Host`.

No `httpx` import here on purpose -- it lives in `core/agent.py` alone. This
module resolves and decides; the agent dials.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

# A resolver takes (host, port) and returns address strings. Injectable so a
# test can answer public once and private on the next call.
Resolver = Callable[[str, int], Sequence[str]]


class EgressError(Exception):
    """The endpoint is not allowed to be dialled."""


def default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EgressError(f"cannot resolve host '{host}': {exc}") from exc
    return [info[4][0] for info in infos]


def normalize_host(host: str) -> str:
    """Lowercase, strip the root dot, and IDNA-encode so comparison is exact."""
    candidate = host.strip().rstrip(".").lower()
    if not candidate:
        raise EgressError("endpoint has no host")
    try:
        return candidate.encode("idna").decode("ascii")
    except UnicodeError:
        # Not IDNA-encodable (an IP literal, or malformed). Compare as-is; if it
        # is an address literal the resolver check below still governs it.
        return candidate


def _public_address(raw: str) -> ipaddress._BaseAddress:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise EgressError(f"resolver returned a non-address: {raw!r}") from exc
    # ::ffff:127.0.0.1 is loopback wearing an IPv6 costume; judge the real one.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if not address.is_global or address.is_multicast or address.is_unspecified:
        raise EgressError(f"endpoint resolves to a non-public address: {address}")
    return address


@dataclass(frozen=True)
class EgressPolicy:
    """Exact, normalized hosts. No wildcards: a wildcard is a bypass waiting to
    be found, and a design partner has a known, small set of endpoints."""

    allowed_hosts: frozenset[str]

    @classmethod
    def from_iterable(cls, hosts: Iterable[str]) -> EgressPolicy:
        return cls(frozenset(normalize_host(h) for h in hosts if h and h.strip()))


@dataclass(frozen=True)
class ValidatedEndpoint:
    url: str
    host: str
    port: int
    address: str

    @property
    def pinned_url(self) -> str:
        """The original URL with the host replaced by the validated address."""
        parts = urlsplit(self.url)
        literal = self.address
        if ":" in literal:  # IPv6 needs brackets in a URL authority
            literal = f"[{literal}]"
        return urlunsplit(parts._replace(netloc=f"{literal}:{self.port}"))

    @property
    def host_header(self) -> str:
        default = 443 if urlsplit(self.url).scheme == "https" else 80
        return self.host if self.port == default else f"{self.host}:{self.port}"


def validate_endpoint(
    endpoint: str,
    policy: EgressPolicy,
    resolver: Resolver = default_resolver,
    *,
    allow_private: bool = False,
) -> ValidatedEndpoint:
    """Resolve and authorize an endpoint, or raise `EgressError`.

    Call this at run start and dial `pinned_url`. Validating and then letting
    the HTTP client resolve the name again reopens the rebinding window.

    `allow_private` relaxes the scheme and address checks for local development
    against a stub on `localhost`. It is deployment-owned -- the worker reads it
    from its own environment -- and is never derived from target configuration,
    because a tenant-settable escape hatch is just the SSRF hole with extra
    steps. The allowlist still applies.
    """
    parts = urlsplit(endpoint)
    if parts.scheme not in ("https", *(("http",) if allow_private else ())):
        raise EgressError(
            f"endpoint must use https, got '{parts.scheme or 'no scheme'}': {endpoint}"
        )
    if parts.username or parts.password:
        raise EgressError("endpoint must not carry credentials in the URL")
    if not parts.hostname:
        raise EgressError(f"endpoint has no host: {endpoint}")

    host = normalize_host(parts.hostname)
    if host not in policy.allowed_hosts:
        raise EgressError(f"host '{host}' is not in the target's allowlist")

    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise EgressError(f"endpoint has an invalid port: {endpoint}") from exc

    addresses = list(resolver(host, port))
    if not addresses:
        raise EgressError(f"host '{host}' resolved to no addresses")
    if allow_private:
        first = str(ipaddress.ip_address(addresses[0]))
    else:
        # Every address, not just the first: a name that resolves to one public
        # and one private address must not be reachable at all.
        first = str([_public_address(a) for a in addresses][0])

    return ValidatedEndpoint(url=endpoint, host=host, port=port, address=first)
