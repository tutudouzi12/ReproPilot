from __future__ import annotations

import asyncio

import pytest

from app.safe_http import open_pinned_pdf, validate_pdf_url


class FakeWriter:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data += data

    async def drain(self):
        return None

    def is_closing(self):
        return self.closed

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


@pytest.mark.asyncio
async def test_safe_transport_connects_to_validated_ip_with_hostname_tls():
    calls = []
    writer = FakeWriter()

    def resolver(host, port, **kwargs):
        return [(2, 1, 6, "", ("151.101.3.42", port))]

    async def opener(host, port, **kwargs):
        calls.append((host, port, kwargs["server_hostname"]))
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nContent-Type: application/pdf\r\n\r\n%PDF")
        reader.feed_eof()
        return reader, writer

    response = await open_pinned_pdf("https://arxiv.org/pdf/1706.03762", resolver=resolver, opener=opener)
    body = b"".join([chunk async for chunk in response.iter_bytes(1024)])

    assert calls == [("151.101.3.42", 443, "arxiv.org")]
    assert b"Host: arxiv.org" in writer.data
    assert body == b"%PDF"


def test_pdf_url_rejects_userinfo_and_header_injection():
    with pytest.raises(ValueError):
        validate_pdf_url("https://user@arxiv.org/pdf/1706.03762")
    with pytest.raises(ValueError):
        validate_pdf_url("https://arxiv.org/pdf/test%0d%0aInjected:yes")
