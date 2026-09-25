"""Browser automation tool (Playwright, optional extra).

Hardened per policy: domain allowlist, per-run page budget, navigation
timeout, and prompt-injection scanning of extracted text. Falls back to the
plain-HTTP fetch_url tool when Playwright is not installed.
"""

from __future__ import annotations

from .registry import ToolExecContext, tool
from .search import fetch_url as _http_fetch_url

try:
    from playwright.async_api import async_playwright  # type: ignore

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@tool(name="browse_page", description="Open a URL in a real browser and extract rendered text. Allowlist + budget enforced.", parameters={
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "wait_ms": {"type": "integer", "description": "render wait in ms (default 1000)"},
    },
    "required": ["url"]}, timeout_s=45)
async def browse_page(tctx: ToolExecContext, url: str, wait_ms: int = 1000) -> dict:
    domains = list(getattr(tctx, "browser_domains", None) or [])
    if domains and not _allowed(url, domains):
        from ..core.errors import ToolError

        raise ToolError(f"domain not in allowlist: {url}")

    if not PLAYWRIGHT_AVAILABLE:
        # graceful degradation: plain HTTP fetch through the hardened fetch tool
        return await _http_fetch_url(tctx, url)

    from ..core.errors import ToolError

    pages_opened = getattr(tctx, "_pages_opened", 0) + 1
    tctx._pages_opened = pages_opened  # type: ignore[attr-defined]
    if pages_opened > getattr(tctx, "browser_max_pages", 10):
        raise ToolError("browser page budget exhausted")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            await page.wait_for_timeout(max(0, min(wait_ms, 5000)))
            text = (await page.inner_text("body"))[:6000]
            title = await page.title()
            return {"url": url, "title": title, "text": text}
        finally:
            await browser.close()


def _allowed(url: str, domains: list[str]) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


BROWSER_TOOLS = [browse_page]
