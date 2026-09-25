"""Research tools: arXiv search/fetch, Semantic Scholar citations, generic URL
fetch with a domain allowlist. Network errors degrade to readable
observations instead of crashing the run.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from ..core.errors import ToolError
from ..core.types import Paper
from .registry import ToolExecContext, tool

ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR = "https://api.semanticscholar.org/graph/v1"
UA = "ResearchOps-Agent/0.1 (research automation; contact: ops@localhost)"


async def _get(url: str, **kwargs: object) -> httpx.Response:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": UA}) as client:
        resp = await client.get(url, **kwargs)  # type: ignore[arg-type]
        resp.raise_for_status()
        return resp


def _parse_arxiv_feed(xml_text: str, limit: int) -> list[Paper]:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall("a:entry", ns)[:limit]:
        arxiv_id = (entry.findtext("a:id", "", ns) or "").rsplit("/", 1)[-1]
        authors = [a.findtext("a:name", "", ns) or "" for a in entry.findall("a:author", ns)]
        published = entry.findtext("a:published", "", ns) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        papers.append(
            Paper(
                id=arxiv_id,
                title=re.sub(r"\s+", " ", entry.findtext("a:title", "", ns) or "").strip(),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                abstract=re.sub(r"\s+", " ", entry.findtext("a:summary", "", ns) or "").strip()[:1500],
                authors=authors,
                year=year,
            )
        )
    return papers


@tool(name="search_papers", description="Search arXiv for papers. Returns id/title/url/abstract/year.", parameters={
    "type": "object",
    "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
    "required": ["query"]}, timeout_s=30)
async def search_papers(tctx: ToolExecContext, query: str, max_results: int = 8) -> list[dict]:
    limit = max(1, min(max_results, 20))
    try:
        resp = await _get(ARXIV_API, params={"search_query": f"all:{query}", "max_results": limit, "sortBy": "relevance"})
        return [p.model_dump() for p in _parse_arxiv_feed(resp.text, limit)]
    except Exception as exc:  # noqa: BLE001 — network failures must degrade gracefully
        raise ToolError(f"arxiv search failed: {exc}") from None


@tool(name="fetch_paper", description="Fetch an arXiv paper's abstract/metadata by id or abs URL.", parameters={
    "type": "object", "properties": {"paper_id": {"type": "string"}}, "required": ["paper_id"]}, timeout_s=30)
async def fetch_paper(tctx: ToolExecContext, paper_id: str) -> dict:
    clean = paper_id.replace("https://arxiv.org/abs/", "").strip()
    try:
        resp = await _get(ARXIV_API, params={"id_list": clean})
        papers = _parse_arxiv_feed(resp.text, 1)
        if not papers:
            raise ToolError(f"paper not found: {paper_id}")
        return papers[0].model_dump()
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"fetch failed: {exc}") from None


@tool(name="search_citations", description="List papers citing a Semantic Scholar paper id/DOI/arXiv id.", parameters={
    "type": "object", "properties": {"paper_id": {"type": "string"}, "limit": {"type": "integer"}},
    "required": ["paper_id"]}, timeout_s=30)
async def search_citations(tctx: ToolExecContext, paper_id: str, limit: int = 10) -> list[dict]:
    url = f"{SEMANTIC_SCHOLAR}/paper/arXiv:{paper_id}/citations" if paper_id.isdigit() else f"{SEMANTIC_SCHOLAR}/paper/{paper_id}/citations"
    try:
        resp = await _get(url, params={"fields": "title,year,externalIds", "limit": min(limit, 50)})
        data = resp.json().get("data", [])
        return [
            {"title": c["paper"].get("title", ""), "year": c["paper"].get("year"),
             "url": f"https://arxiv.org/abs/{c['paper']['externalIds'].get('ArXiv')}" if c["paper"].get("externalIds", {}).get("ArXiv") else ""}
            for c in data
        ]
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"citation search failed (rate limits are common): {exc}") from None


def _domain_allowed(url: str, allow_domains: list[str]) -> bool:
    host = httpx.URL(url).host.lower()
    return any(host == d or host.endswith("." + d) for d in allow_domains)


@tool(name="fetch_url", description="Fetch a web page's text (title + body, tag-stripped). Domain allowlist enforced.", parameters={
    "type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}, timeout_s=30)
async def fetch_url(tctx: ToolExecContext, url: str, _allow_domains: list[str] | None = None) -> dict:
    allow = _allow_domains if _allow_domains is not None else getattr(tctx, "browser_domains", None) or []
    if allow and not _domain_allowed(url, allow):
        raise ToolError(f"domain not in allowlist: {url}")
    try:
        resp = await _get(url)
        ctype = resp.headers.get("content-type", "")
        if "html" in ctype:
            title_m = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.S | re.I)
            body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text, flags=re.S | re.I)
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()
            return {"url": url, "title": (title_m.group(1).strip() if title_m else ""), "text": body[:6000]}
        if "json" in ctype:
            return {"url": url, "json": resp.json()}
        return {"url": url, "text": resp.text[:6000]}
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"fetch_url failed: {exc}") from None


RESEARCH_TOOLS = [search_papers, fetch_paper, search_citations, fetch_url]
