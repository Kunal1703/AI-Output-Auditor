"""Content extraction — URL and file (Document 4, §2/§7).

Real trafilatura, real pypdf, real BeautifulSoup. Only the network is mocked.

**Extraction quality is an audit-correctness concern.** Leave a nav menu in the
text and Readability reports poor structure the author never wrote; drop a
section and Coverage reports an omission that does not exist. A bad extraction
does not produce a bad-looking report — it produces a *confident* report about
the wrong text. These tests hold that line.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ExtractionError, UnsupportedInputError
from app.preprocessing.content_extractor import DefaultContentExtractor
from app.preprocessing.input_router import DefaultInputRouter
from app.shared.schemas import InputType

pytestmark = pytest.mark.unit

ARTICLE_HTML = """<!DOCTYPE html>
<html><head><title>Rate limiting explained</title></head>
<body>
  <nav><a href="/">Home</a> <a href="/jobs">We're hiring!</a></nav>
  <header><div class="cookie-banner">We use cookies. Accept all?</div></header>
  <article>
    <h1>Rate limiting explained</h1>
    <p>Rate limiting caps how many requests a client may make in a window of time.
       It protects a service from being overwhelmed, whether by a runaway script or
       a deliberate flood of traffic from a malicious source somewhere.</p>
    <p>The most common approach is the token bucket. Each client holds a bucket that
       refills at a fixed rate. A request costs one token, and when the bucket is
       empty the request is rejected until it refills again.</p>
  </article>
  <aside><p>Subscribe to our newsletter for more!</p></aside>
  <footer>Copyright 2026. All rights reserved.</footer>
  <script>analytics.track('pageview');</script>
</body></html>"""

PROSE = (
    b"Rate limiting caps how many requests a client may make in a window of time. "
    b"The token bucket refills at a fixed rate and each request costs one token "
    b"from that bucket, which allows short bursts."
)


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def serve(status=200, body=ARTICLE_HTML):
    def handle(request):
        return httpx.Response(status, text=body, headers={"content-type": "text/html"})

    return handle


def make_pdf(pages: list[str]) -> bytes:
    """A minimal but genuinely valid PDF with a real text layer.

    Hand-rolled so the pypdf path is exercised without a test-only dependency on
    reportlab. An extractor I claim to support but never run is a claim, not a
    feature.
    """
    objects: list[bytes] = []

    def obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content_ids = []
    for text in pages:
        lines = b"\n".join(
            b"(" + line.encode("latin-1") + b") Tj T*" for line in text.split("\n")
        )
        stream = b"BT /F1 12 Tf 72 720 Td 14 TL\n" + lines + b"\nET"
        content_ids.append(
            obj(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                + stream + b"\nendstream")
        )
    pages_id = len(objects) + len(pages) + 1
    page_ids = [
        obj(b"<< /Type /Page /Parent " + str(pages_id).encode()
            + b" 0 R /MediaBox [0 0 612 792] /Contents " + str(cid).encode()
            + b" 0 R /Resources << /Font << /F1 " + str(font).encode() + b" 0 R >> >> >>")
        for cid in content_ids
    ]
    kids = b" ".join(str(p).encode() + b" 0 R" for p in page_ids)
    obj(b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode() + b" >>")
    catalog = obj(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root "
            + str(catalog).encode() + b" 0 R >>\nstartxref\n"
            + str(xref_at).encode() + b"\n%%EOF\n")
    return bytes(out)


# --------------------------------------------------------------------------- #
# URL
# --------------------------------------------------------------------------- #


async def test_url_extracts_the_article(settings):
    got = await DefaultContentExtractor(settings, client=client_for(serve())).from_url(
        "https://example.org/a"
    )
    assert "token bucket" in got.text
    assert got.extractor in ("trafilatura", "beautifulsoup")
    assert got.source_uri == "https://example.org/a"


@pytest.mark.parametrize(
    "junk",
    ["We're hiring", "cookie", "newsletter", "All rights reserved", "analytics.track"],
)
async def test_url_strips_boilerplate(settings, junk):
    """Boilerplate in the text becomes a measurement about the wrong document."""
    got = await DefaultContentExtractor(settings, client=client_for(serve())).from_url(
        "https://example.org/a"
    )
    assert junk not in got.text


@pytest.mark.parametrize("status", [404, 500])
async def test_url_http_error_raises(settings, status):
    """Unlike Credibility's fetch, a failure here means there is nothing to audit."""
    with pytest.raises(ExtractionError):
        await DefaultContentExtractor(settings, client=client_for(serve(status))).from_url(
            "https://example.org/a"
        )


async def test_url_paywall_stub_raises_rather_than_auditing_nothing(settings):
    stub = "<html><head><title>Members</title></head><body><p>Subscribe.</p></body></html>"
    with pytest.raises(ExtractionError, match="Paste the text"):
        await DefaultContentExtractor(
            settings, client=client_for(serve(body=stub))
        ).from_url("https://example.org/members")


async def test_non_url_is_rejected(settings):
    with pytest.raises(UnsupportedInputError):
        await DefaultContentExtractor(settings, client=client_for(serve())).from_url(
            "not-a-url"
        )


async def test_network_failure_raises_extraction_error(settings):
    def boom(request):
        raise httpx.ConnectError("dns", request=request)

    with pytest.raises(ExtractionError):
        await DefaultContentExtractor(settings, client=client_for(boom)).from_url(
            "https://nope.invalid/x"
        )


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #


async def test_markdown_file(settings):
    ex = DefaultContentExtractor(settings, client=client_for(serve()))
    got = await ex.from_file("notes.md", b"# Rate limiting\n\n" + PROSE)
    assert "token bucket" in got.text
    assert got.title == "Rate limiting"
    assert got.extractor == "plain"


async def test_plain_text_and_bom(settings):
    ex = DefaultContentExtractor(settings, client=client_for(serve()))
    assert "token bucket" in (await ex.from_file("a.txt", PROSE)).text
    got = await ex.from_file("bom.txt", b"\xef\xbb\xbf" + PROSE)
    assert not got.text.startswith("﻿")


async def test_html_file(settings):
    ex = DefaultContentExtractor(settings, client=client_for(serve()))
    got = await ex.from_file("page.html", ARTICLE_HTML.encode())
    assert "token bucket" in got.text
    assert "We're hiring" not in got.text


async def test_pdf_file(settings):
    ex = DefaultContentExtractor(settings, client=client_for(serve()))
    pdf = make_pdf([
        "Rate limiting caps how many requests a client may make.",
        "The token bucket refills at a fixed rate, one token per request.",
    ])
    got = await ex.from_file("paper.pdf", pdf)
    assert "token bucket" in got.text.lower()
    assert got.extractor == "pypdf"
    # Pages joined with a paragraph break: a page edge is not a sentence edge.
    assert "\n\n" in got.text


@pytest.mark.parametrize(
    "filename, data, error",
    [
        ("virus.exe", b"MZ" + b"x" * 300, UnsupportedInputError),
        ("empty.txt", b"", ExtractionError),
        ("stub.txt", b"hi", ExtractionError),
        ("huge.txt", b"x" * (11 * 1024 * 1024), UnsupportedInputError),
        ("fake.pdf", b"not a pdf at all" * 20, ExtractionError),
    ],
    ids=["unsupported", "empty", "too-short", "oversize", "corrupt-pdf"],
)
async def test_file_rejections(settings, filename, data, error):
    ex = DefaultContentExtractor(settings, client=client_for(serve()))
    with pytest.raises(error):
        await ex.from_file(filename, data)


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


async def test_router_produces_a_usable_context(settings):
    router = DefaultInputRouter(
        DefaultContentExtractor(settings, client=client_for(serve()))
    )

    ctx = await router.from_url("aud_1", "https://example.org/a", prompt="Explain it.")
    assert ctx.input_type is InputType.URL
    assert ctx.source_uri == "https://example.org/a"
    assert ctx.has_prompt
    assert "token bucket" in ctx.ai_output
    # Provenance reaches the engines — a surprising report is traceable to the
    # extractor that produced its text.
    assert ctx.metadata.extra["extractor"] in ("trafilatura", "beautifulsoup")
    assert len(ctx.sentences) >= 2

    ctx = await router.from_file("aud_2", "notes.md", b"# T\n\n" + PROSE)
    assert ctx.input_type is InputType.FILE
    assert ctx.source_uri == "notes.md"

    ctx = await router.from_text("aud_3", "  padded  ")
    assert ctx.input_type is InputType.TEXT
    assert ctx.ai_output == "padded"  # normalized, never altered
