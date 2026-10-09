"""Outbound policy verifies resolved addresses, not just URL spelling."""

import asyncio
import socket

import httpcore
import httpx
import pytest

from agentskills_http import HTTPStaticFileSkillProvider
from agentskills_http.network import GuardedBackend, NetworkPolicyError, _translate_errors


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "100.64.0.1",
    ],
)
async def test_given_private_dns_answer_when_connecting_then_blocked(address, monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(NetworkPolicyError):
        await GuardedBackend().connect_tcp("public.example", 443)


@pytest.mark.parametrize("private", [False, True])
async def test_given_approved_address_when_connecting_then_ip_is_pinned(private, monkeypatch):
    address = "127.0.0.1" if private else "93.184.216.34"
    backend = GuardedBackend(allow_private_network=private)

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    async def connect(host, port, *args):
        assert (host, port) == (address, 443)
        return "connected"

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(backend._backend, "connect_tcp", connect)
    assert await backend.connect_tcp("changing.example", 443) == "connected"


async def test_given_mixed_dns_answers_when_connecting_then_all_answers_are_checked(monkeypatch):
    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            for address in ["93.184.216.34", "127.0.0.1"]
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(NetworkPolicyError):
        await GuardedBackend().connect_tcp("mixed.example", 443)


@pytest.mark.parametrize(
    "error,expected",
    [(OSError("secret"), httpcore.ConnectError), (TimeoutError("secret"), httpcore.ConnectTimeout)],
)
async def test_given_dns_failure_when_connecting_then_error_is_sanitized(
    monkeypatch, error, expected
):
    async def resolve(*args, **kwargs):
        raise error

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(expected) as caught:
        await GuardedBackend().connect_tcp("secret.example", 443)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "error,expected",
    [
        (httpcore.ConnectTimeout, httpx.TimeoutException),
        (httpcore.ConnectError, httpx.NetworkError),
        (httpcore.RemoteProtocolError, httpx.ProtocolError),
    ],
)
def test_given_core_error_when_adapted_then_public_error_is_sanitized(error, expected):
    with pytest.raises(expected) as caught, _translate_errors():
        raise error("secret")
    assert "secret" not in str(caught.value)


async def test_given_empty_dns_answer_when_connecting_then_outage(monkeypatch):
    async def resolve(*args, **kwargs):
        return []

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(httpcore.ConnectError):
        await GuardedBackend().connect_tcp("empty.example", 443)


@pytest.mark.parametrize("address", ["224.0.0.1", "ff0e::1", "240.0.0.1"])
async def test_given_non_unicast_answer_when_connecting_then_blocked(monkeypatch, address):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(NetworkPolicyError):
        await GuardedBackend().connect_tcp("non-unicast.example", 443)


@pytest.mark.parametrize(
    "url",
    [
        "file:///secret",
        "https://user:secret@example.com",
        "https://example.com/?sig=secret",
        "https://example.com/#secret",
    ],
)
def test_given_unsafe_base_url_when_constructing_then_secret_is_not_echoed(url):
    with pytest.raises(ValueError) as caught:
        HTTPStaticFileSkillProvider(url)
    assert "secret" not in str(caught.value)


def test_given_non_boolean_private_opt_in_when_constructing_then_rejected():
    with pytest.raises(ValueError, match="boolean"):
        HTTPStaticFileSkillProvider("https://example.com", allow_private_network="false")


async def test_given_custom_client_when_no_explicit_opt_out_then_rejected():
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="custom client"):
            HTTPStaticFileSkillProvider("https://example.com", client=client)


async def test_given_real_loopback_server_when_explicitly_allowed_then_transport_streams():
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ndata")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async with await asyncio.start_server(handle, "127.0.0.1", 0) as listener:
        port = listener.sockets[0].getsockname()[1]
        with pytest.warns(UserWarning):
            provider = HTTPStaticFileSkillProvider(
                f"http://127.0.0.1:{port}", allow_private_network=True
            )
        async with provider:
            assert await provider.get_asset("alpha", "data.bin") == b"data"
        with pytest.warns(UserWarning):
            blocked = HTTPStaticFileSkillProvider(f"http://127.0.0.1:{port}")
        async with blocked:
            with pytest.raises(NetworkPolicyError):
                await blocked.get_asset("alpha", "data.bin")
