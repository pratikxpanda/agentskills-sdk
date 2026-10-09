"""DNS-pinned outbound HTTP transport with explicit private-network policy."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

import httpcore
import httpx

from agentskills_core.exceptions import AgentSkillsError


class NetworkPolicyError(AgentSkillsError):
    """A destination or redirect violates configured outbound policy."""


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Resolve once per connection, validate every answer, and connect to an IP.

    HTTPcore retains the original hostname for TLS SNI and certificate checks.
    No proxy or environment-selected transport can bypass this backend.
    """

    def __init__(self, *, allow_private_network: bool = False) -> None:
        self._allow_private = allow_private_network
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        """Connect only to an address from this request's validated DNS answer."""
        try:
            async with asyncio.timeout(timeout):
                answers = await asyncio.get_running_loop().getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                )
                addresses = [answer[4][0] for answer in answers]
                if not addresses:
                    raise httpcore.ConnectError("Destination did not resolve")
                for address in addresses:
                    parsed = ipaddress.ip_address(address.split("%", 1)[0])
                    mapped = getattr(parsed, "ipv4_mapped", None)
                    if not self._allow_private and (
                        not parsed.is_global
                        or parsed.is_multicast
                        or parsed.is_reserved
                        or (mapped is not None and not mapped.is_global)
                        or "%" in address
                    ):
                        raise NetworkPolicyError("Destination is not a public network address")
                return await self._backend.connect_tcp(
                    addresses[0], port, timeout, local_address, socket_options
                )
        except TimeoutError:
            raise httpcore.ConnectTimeout("Destination connection timed out") from None
        except OSError:
            raise httpcore.ConnectError("Destination resolution or connection failed") from None


@contextmanager
def _translate_errors() -> Iterator[None]:
    try:
        yield
    except httpcore.TimeoutException:
        raise httpx.TimeoutException("HTTP transport timed out") from None
    except httpcore.NetworkError:
        raise httpx.NetworkError("HTTP network failure") from None
    except httpcore.ProtocolError:
        raise httpx.ProtocolError("HTTP protocol failure") from None


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self._response = response

    async def __aiter__(self) -> AsyncIterator[bytes]:
        with _translate_errors():
            async for chunk in self._response.aiter_stream():
                yield chunk

    async def aclose(self) -> None:
        with _translate_errors():
            await self._response.aclose()


class GuardedTransport(httpx.AsyncBaseTransport):
    """HTTPX adapter using public HTTPcore interfaces and a guarded network backend."""

    def __init__(self, *, allow_private_network: bool = False) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=GuardedBackend(allow_private_network=allow_private_network),
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=5,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send the original hostname and headers through the DNS-pinned pool."""
        with _translate_errors():
            response = await self._pool.handle_async_request(
                httpcore.Request(
                    method=request.method,
                    url=httpcore.URL(
                        scheme=request.url.raw_scheme,
                        host=request.url.raw_host,
                        port=request.url.port,
                        target=request.url.raw_path,
                    ),
                    headers=request.headers.raw,
                    content=request.stream,
                    extensions=request.extensions,
                )
            )
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_ResponseStream(response),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        """Close only the connections owned by this transport."""
        await self._pool.aclose()
