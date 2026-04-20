from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RegulationUnit
from app.retrieval.embedder import ConfigurableEmbedder


DEFAULT_EURLEX_OJ_URL = "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"


@dataclass(frozen=True)
class ParsedUnit:
    unit_id: str
    title: str
    text: str


_ARTICLE_RE = re.compile(r"^Article\s+(\d+)\b", re.IGNORECASE)


def _clean_text(s: str) -> str:
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def parse_eurlex_html_to_articles(*, html: str) -> list[ParsedUnit]:
    """
    Best-effort EUR-Lex HTML parser.

    EUR-Lex markup varies; this aims to extract 'Article N' sections.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "EU AI Act ingestion requires BeautifulSoup. Install backend deps: `pip install -r backend/requirements.txt`"
        ) from e

    soup = BeautifulSoup(html, "lxml")
    # Prefer the main content container; fall back to body.
    root = soup.find("div", {"id": "TexteOnly"}) or soup.body or soup

    # Collect headings and subsequent siblings until next heading.
    headings = root.find_all(["h1", "h2", "h3", "p"])
    units: list[ParsedUnit] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = _clean_text("\n".join(current.get("parts") or []))
        if text:
            units.append(ParsedUnit(unit_id=current["unit_id"], title=current.get("title") or "", text=text))
        current = None

    for el in headings:
        txt = _clean_text(el.get_text(" ", strip=True) or "")
        if not txt:
            continue
        m = _ARTICLE_RE.match(txt)
        if m:
            flush()
            n = m.group(1)
            current = {"unit_id": f"Art. {n}", "title": txt, "parts": []}
            continue
        if current:
            # Add paragraph-ish content.
            if el.name in {"p", "h3"}:
                current["parts"].append(el.get_text(" ", strip=True))

    flush()
    # If parsing fails, return empty list so caller can fall back to seeded content.
    return units


async def ingest_eu_ai_act_from_eurlex(
    *,
    session: AsyncSession,
    url: str = DEFAULT_EURLEX_OJ_URL,
    version: str = "eurlex-eli-reg-2024-1689-oj",
    effective_from: datetime | None = None,
) -> dict[str, Any]:
    """
    Fetches EU AI Act from EUR-Lex and upserts Article units.
    """
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        res = await client.get(url, headers={"accept": "text/html"})
        res.raise_for_status()
        html = res.text

    units = parse_eurlex_html_to_articles(html=html)
    embedder = ConfigurableEmbedder()

    inserted = 0
    updated = 0
    embedded = 0

    for u in units:
        meta = {
            "jurisdiction": "EU",
            "source_url": url,
            "source_doc_id": "EUR-LEX:REG:2024:1689:OJ",
            "citation": {"type": "article", "id": u.unit_id},
            "ingested_at": datetime.utcnow().isoformat(),
        }

        text_for_embedding = (u.title + "\n" + u.text).strip()
        emb: list[float] | None = None
        if text_for_embedding:
            try:
                emb = (await embedder.embed(text=text_for_embedding)).vector
            except Exception:  # noqa: BLE001
                emb = None

        existing = (
            (
                await session.execute(
                    select(RegulationUnit)
                    .where(RegulationUnit.regulation_code == "EU_AI_ACT")
                    .where(RegulationUnit.framework_code == "EU_AI_ACT")
                    .where(RegulationUnit.unit_id == u.unit_id)
                )
            )
            .scalars()
            .first()
        )
        if existing:
            existing.title = u.title
            existing.text = u.text
            existing.version = version
            existing.meta = meta
            existing.framework_code = "EU_AI_ACT"
            existing.jurisdiction = "EU"
            existing.source_url = url
            existing.source_doc_id = meta["source_doc_id"]
            existing.effective_from = effective_from
            if emb:
                existing.embedding = emb
                embedded += 1
            await session.merge(existing)
            updated += 1
        else:
            session.add(
                RegulationUnit(
                    regulation_code="EU_AI_ACT",
                    framework_code="EU_AI_ACT",
                    unit_id=u.unit_id,
                    title=u.title,
                    text=u.text,
                    version=version,
                    meta=meta,
                    jurisdiction="EU",
                    source_url=url,
                    source_doc_id=meta["source_doc_id"],
                    effective_from=effective_from,
                    embedding=emb,
                )
            )
            inserted += 1
            if emb:
                embedded += 1

    await session.commit()
    return {"url": url, "parsed_units": len(units), "inserted": inserted, "updated": updated, "embedded": embedded}

