"""ArXiv tool — specific search and daily discover."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import arxiv

from config.settings import get_settings
from core.db import atomic_write
from tools.base import BaseTool

logger = logging.getLogger(__name__)

_DISCOVER_MAX_PER_KEYWORD = 50
_SUMMARY_TRUNCATE = 400


class ArxivTool(BaseTool):
    tool_name = "arxiv"

    async def run_local(self, params: dict) -> None:
        mode = params.get("mode", "search")
        if mode == "discover":
            await self._daily_discover(params)
        else:
            await self._specific_search(params)

    def get_spawn_cmd(self, params: dict) -> str:
        import json
        params_json = json.dumps(params)
        return f"python -m tools.arxiv_runner '{params_json}'"

    # ------------------------------------------------------------------

    async def _specific_search(self, params: dict) -> None:
        """Search ArXiv by paper ID or title keywords."""
        query = params.get("query", "")
        paper_id = params.get("id", "")
        max_results = params.get("max_results", 10)

        if not query and not paper_id:
            raise ValueError("ArXiv search requires 'query' or 'id' in params")

        if paper_id:
            search = arxiv.Search(id_list=[paper_id])
            slug = paper_id.replace("/", "_")
        else:
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            slug = "query"

        logger.info("ArXiv specific search: id=%r query=%r", paper_id, query)
        client = arxiv.Client()
        papers = await asyncio.to_thread(list, client.results(search))

        content = self._format_papers(f"ArXiv: {query or paper_id}", papers)
        self._write_output(f"arxiv_search_{slug}.md", content, params.get("_task_id"))

    async def _daily_discover(self, params: dict) -> None:
        """Fetch papers submitted in the last 24 h matching user interests."""
        since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        settings = get_settings()
        keywords = params.get("keywords") or settings.arxiv_discover_keywords

        logger.info(
            "ArXiv daily discover since %s, keywords=%s",
            since.isoformat(), keywords,
        )

        client = arxiv.Client()
        seen: set[str] = set()
        papers: list = []

        for kw in keywords:
            search = arxiv.Search(
                query=kw,
                max_results=_DISCOVER_MAX_PER_KEYWORD,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )
            results = await asyncio.to_thread(list, client.results(search))
            for paper in results:
                if paper.published < since:
                    break  # results are date-descending; nothing later will qualify
                if paper.entry_id not in seen:
                    seen.add(paper.entry_id)
                    papers.append(paper)

        generated_at = datetime.now(tz=timezone.utc)
        content = self._format_papers(
            f"ArXiv Daily Discover — {generated_at.strftime('%Y-%m-%d')}",
            papers,
            generated_at=generated_at,
        )
        self._write_output("arxiv_daily_discover.md", content, params.get("_task_id"))

    # ------------------------------------------------------------------

    def _format_papers(
        self,
        heading: str,
        papers: list,
        generated_at: datetime | None = None,
    ) -> str:
        lines: list[str] = [f"# {heading}", ""]
        if generated_at:
            lines += [f"_Generated: {generated_at.strftime('%Y-%m-%dT%H:%M UTC')}_", ""]

        if not papers:
            lines.append("_No papers found._")
            return "\n".join(lines)

        lines += [f"_{len(papers)} paper(s)_", ""]

        for i, paper in enumerate(papers, 1):
            short_id = paper.entry_id.split("/abs/")[-1]
            authors = ", ".join(a.name for a in paper.authors[:3])
            if len(paper.authors) > 3:
                authors += " et al."
            published = (
                paper.published.strftime("%Y-%m-%d") if paper.published else "unknown"
            )
            categories = ", ".join(paper.categories[:3])
            summary = paper.summary.replace("\n", " ").strip()
            if len(summary) > _SUMMARY_TRUNCATE:
                summary = summary[:_SUMMARY_TRUNCATE] + "…"
            pdf = paper.pdf_url or f"https://arxiv.org/pdf/{short_id}"

            lines += [
                f"## {i}. {paper.title}",
                f"**ID:** `{short_id}`  ",
                f"**Authors:** {authors}  ",
                f"**Published:** {published}  ",
                f"**Categories:** {categories}  ",
                f"[Abstract](https://arxiv.org/abs/{short_id}) | [PDF]({pdf})",
                "",
                f"> {summary}",
                "",
                "---",
                "",
            ]

        return "\n".join(lines)

    def _write_output(self, filename: str, content: str, task_id: int | None = None) -> None:
        settings = get_settings()
        prefix = f"{task_id}_" if task_id is not None else ""
        out_path = Path(settings.brain_inbox) / f"{prefix}{filename}"
        atomic_write(out_path, content)
        logger.info("ArXiv output written to %s", out_path)
