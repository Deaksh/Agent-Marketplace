from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentPackage, AgentVersion

# Demo marketplace rows: `runtime=builtin` agents already registered in AgentRegistry.
_DEMO_PACKAGES: list[dict[str, Any]] = [
    {
        "publisher": "Outcome Execution Layer",
        "slug": "demo-regulation-retriever",
        "name": "Regulation evidence retriever",
        "description": "Pulls ranked regulation unit snippets (keyword + optional embedding rerank) for the active workflow.",
        "categories": ["retrieval", "evidence"],
        "tags": ["builtin", "demo", "GDPR"],
        "version": "0.1.0",
        "release_notes": "Demo package wrapping the built-in regulation_retriever agent.",
        "runtime": "builtin",
        "builtin_agent_name": "regulation_retriever",
        "cost_estimate_usd": 0.0,
        "reliability_score": 0.85,
    },
    {
        "publisher": "Outcome Execution Layer",
        "slug": "demo-risk-scorer",
        "name": "Compliance risk scorer",
        "description": "Turns obligations, gaps, and context into a structured risk score and mitigation hints.",
        "categories": ["risk", "assessment"],
        "tags": ["builtin", "demo"],
        "version": "0.1.0",
        "release_notes": "Demo package wrapping the built-in risk_scorer agent.",
        "runtime": "builtin",
        "builtin_agent_name": "risk_scorer",
        "cost_estimate_usd": 0.0,
        "reliability_score": 0.82,
    },
    {
        "publisher": "Outcome Execution Layer",
        "slug": "demo-report-generator",
        "name": "Explainable compliance report",
        "description": "Produces a human-readable report with persona-aware recommendations.",
        "categories": ["reporting", "explainability"],
        "tags": ["builtin", "demo"],
        "version": "0.1.0",
        "release_notes": "Demo package wrapping the built-in report_generator agent.",
        "runtime": "builtin",
        "builtin_agent_name": "report_generator",
        "cost_estimate_usd": 0.0,
        "reliability_score": 0.8,
    },
]


async def seed_marketplace_packages(*, session: AsyncSession) -> dict[str, Any]:
    """
    Idempotent dev/demo seed for `agent_package` + `agent_version`.

    Skips any slug that already exists. Does not remove or update existing rows.
    """
    inserted = 0
    skipped: list[str] = []
    created: list[str] = []

    for row in _DEMO_PACKAGES:
        slug = row["slug"]
        existing = (await session.execute(select(AgentPackage).where(AgentPackage.slug == slug))).scalars().first()
        if existing:
            skipped.append(slug)
            continue

        pkg = AgentPackage(
            publisher=row["publisher"],
            slug=slug,
            name=row["name"],
            description=row["description"],
            categories=list(row.get("categories") or []),
            tags=list(row.get("tags") or []),
        )
        session.add(pkg)
        await session.commit()
        await session.refresh(pkg)

        ver = AgentVersion(
            package_id=pkg.id,
            version=row["version"],
            release_notes=row.get("release_notes") or "",
            runtime=row["runtime"],
            builtin_agent_name=row.get("builtin_agent_name"),
            endpoint_url=row.get("endpoint_url"),
            prompt_template=row.get("prompt_template"),
            input_schema=dict(row.get("input_schema") or {}),
            output_schema=dict(row.get("output_schema") or {}),
            cost_estimate_usd=float(row.get("cost_estimate_usd") or 0.0),
            reliability_score=float(row.get("reliability_score") or 0.8),
            status="active",
        )
        session.add(ver)
        await session.commit()
        inserted += 1
        created.append(slug)

    return {
        "inserted_packages": inserted,
        "skipped_existing_slugs": skipped,
        "created_slugs": created,
    }
