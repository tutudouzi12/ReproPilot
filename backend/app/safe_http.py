from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable
from urllib.parse import unquote, urlparse


Resolver = Callable[..., list[tuple]]
Opener = Callable[..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


@dataclass
class PinnedHTTPSResponse:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    status_code: int
    headers: dict[str, str]

    async def iter_bytes(self, max_bytes: int) -> AsyncIterator[bytes]:
        total = 0
        try:
            if "chunked" in self.headers.get("transfer-encoding", "").lower():
                async for chunk in _iter_chunked(self.reader):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("remote PDF exceeds configured size limit")
                    yield chunk
            else:
                expected = int(self.headers.get("content-length", "0") or 0)
                if expected > max_bytes:
                    raise ValueError("remote PDF exceeds configured size limit")
                while True:
                    chunk = await self.reader.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("remote PDF exceeds configured size limit")
                    yield chunk
        finally:
            await self.close()

    async def close(self) -> None:
        if not self.writer.is_closing():
            self.writer.close()
            await self.writer.wait_closed()


def validate_pdf_url(url: str) -> tuple[str, int, str]:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"arxiv.org", "export.arxiv.org"}
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("only HTTPS arxiv PDF URLs are allowed")
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    decoded_target = unquote(target)
    if any(character in decoded_target for character in ("\r", "\n", "\x00")):
        raise ValueError("invalid PDF request target")
    return parsed.hostname, 443, target


def resolve_public_addresses(host: str, port: int, resolver: Resolver | None = None) -> list[str]:
    resolver = resolver or socket.getaddrinfo
    try:
        records = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("PDF host cannot be resolved") from exc
    addresses = []
    for record in records:
        address = record[4][0]
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("PDF host resolved to a non-public address")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError("PDF host has no public address")
    return addresses


async def open_pinned_pdf(
    url: str,
    *,
    resolver: Resolver | None = None,
    opener: Opener | None = None,
) -> PinnedHTTPSResponse:
    host, port, target = validate_pdf_url(url)
    addresses = resolve_public_addresses(host, port, resolver)
    opener = opener or asyncio.open_connection
    context = ssl.create_default_context()
    last_error: Exception | None = None
    reader = writer = None
    for address in addresses:
        try:
            reader, writer = await opener(address, port, ssl=context, server_hostname=host)
            break
        except (OSError, ssl.SSLError) as exc:
            last_error = exc
    if reader is None or writer is None:
        raise OSError(f"unable to connect to validated PDF address: {last_error}")
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: ReproPilot/1.0\r\n"
        "Accept: application/pdf\r\n"
        "Connection: close\r\n\r\n"
    )
    writer.write(request.encode("ascii"))
    await writer.drain()
    try:
        raw_headers = await reader.readuntil(b"\r\n\r\n")
        if len(raw_headers) > 64 * 1024:
            raise ValueError("remote PDF response headers are too large")
        lines = raw_headers.decode("iso-8859-1").split("\r\n")
        status_parts = lines[0].split(" ", 2)
        if len(status_parts) < 2 or not status_parts[1].isdigit():
            raise ValueError("invalid remote PDF HTTP status")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            name, separator, value = line.partition(":")
            if not separator:
                raise ValueError("invalid remote PDF response header")
            headers[name.strip().lower()] = value.strip()
        return PinnedHTTPSResponse(reader, writer, int(status_parts[1]), headers)
    except Exception:
        writer.close()
        await writer.wait_closed()
        raise


async def _iter_chunked(reader: asyncio.StreamReader) -> AsyncIterator[bytes]:
    while True:
        size_line = await reader.readline()
        if not size_line:
            raise ValueError("truncated chunked PDF response")
        try:
            size = int(size_line.split(b";", 1)[0].strip(), 16)
        except ValueError as exc:
            raise ValueError("invalid chunked PDF response") from exc
        if size == 0:
            while await reader.readline() not in {b"\r\n", b"", b"\n"}:
                pass
            return
        chunk = await reader.readexactly(size)
        if await reader.readexactly(2) != b"\r\n":
            raise ValueError("invalid chunk delimiter in PDF response")
        yield chunk
