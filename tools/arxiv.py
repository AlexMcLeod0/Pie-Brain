"""ArXiv tool — specific search and daily discover."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import arxiv

from config.settings import get_settings
from core.utils import atomic_write
from tools.base import BaseTool

logger = logging.getLogger(__name__)

_DISCOVER_MAX_PER_KEYWORD = 50
_SUMMARY_TRUNCATE = 400


class ArxivTool(BaseTool):
    tool_name = "arxiv"
    routing_description = "search or fetch research papers by query, ID, or daily discovery"
    routing_examples = [
        (
            "Can you find me papers on transformer architecture?",
            '{"query": "transformer architecture", "mode": "search"}',
        ),
        (
            "Pull the latest papers on reinforcement learning from arxiv",
            '{"query": "reinforcement learning", "mode": "discover"}',
        ),
    ]

    def __init__(self) -> None:
        self._fetched_papers: list = []  # populated during run_local, read in post_task

    async def run_local(self, params: dict) -> None:
        self._fetched_papers = []
        mode = params.get("mode", "search")
        if mode == "discover":
            await self._daily_discover(params)
        else:
            await self._specific_search(params)

    async def post_task(self, params: dict, result: str | None) -> None:
        """Store each fetched paper (title + full abstract) to LanceDB memory."""
        if not self._fetched_papers:
            return

        from tools.memory import MemoryTool
        memory = MemoryTool()

        retrieved_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        for paper in self._fetched_papers:
            short_id = paper.entry_id.split("/abs/")[-1]
            authors = ", ".join(a.name for a in paper.authors[:5])
            content = (
                f"{paper.title}\n\n"
                f"Authors: {authors}\n"
                f"Published: {paper.published.strftime('%Y-%m-%d') if paper.published else 'unknown'}\n"
                f"Retrieved: {retrieved_at}\n\n"
                f"{paper.summary.replace(chr(10), ' ').strip()}"
            )
            # _store handles dedup internally (logs duplicates at INFO level)
            await memory._store({"content": content, "source_path": short_id})

        logger.info("ArXiv post-task: submitted %d paper(s) to memory.", len(self._fetched_papers))

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
        self._fetched_papers.extend(papers)

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
        self._fetched_papers.extend(papers)

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
