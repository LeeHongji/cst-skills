from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jieba

from .markdown import read_page, sha256_file, strip_markdown, wikilinks
from .paths import BrainPaths


ASCII_TOKEN = re.compile(
    r"[A-Za-z]+(?:[-_.][A-Za-z0-9]+)*|[A-Za-z]*\d+(?:[.,]\d+)?[A-Za-z]*|[\u0370-\u03ff]+"
)
HAN_RUN = re.compile(r"[\u3400-\u9fff]+")


def tokenize(text: str) -> list[str]:
    normalized = text.casefold()
    tokens = [token for token in ASCII_TOKEN.findall(normalized) if token]
    for run in HAN_RUN.findall(normalized):
        segmented = [token.strip() for token in jieba.cut(run) if token.strip()]
        tokens.extend(segmented)
        if len(run) > 1:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


class BrainIndex:
    def __init__(self, paths: BrainPaths | None = None):
        self.paths = paths or BrainPaths.resolve()
        self.paths.ensure()

    def _page_files(self) -> list[Path]:
        candidates = list(self.paths.wiki.rglob("*.md"))
        candidates.extend(self.paths.inbox.rglob("*.md"))
        candidates.extend(self.paths.meta.glob("*.md"))
        return sorted({path.resolve() for path in candidates})

    def _fingerprints(self) -> dict[str, str]:
        return {
            path.relative_to(self.paths.root).as_posix(): sha256_file(path)
            for path in self._page_files()
        }

    def build(self) -> dict[str, Any]:
        documents: list[dict[str, Any]] = []
        document_frequency: Counter[str] = Counter()
        fingerprints = self._fingerprints()
        for relative in fingerprints:
            path = self.paths.root / relative
            metadata, body = read_page(path)
            title = str(metadata.get("title") or path.stem)
            aliases = metadata.get("aliases") or []
            tags = metadata.get("tags") or []
            searchable = " ".join(
                [
                    title,
                    " ".join(map(str, aliases if isinstance(aliases, list) else [aliases])),
                    " ".join(map(str, tags if isinstance(tags, list) else [tags])),
                    strip_markdown(body),
                ]
            )
            tokens = tokenize(searchable)
            counts = Counter(tokens)
            document_frequency.update(counts.keys())
            documents.append(
                {
                    "path": relative,
                    "id": metadata.get("id"),
                    "title": title,
                    "type": metadata.get("type"),
                    "status": metadata.get("status"),
                    "aliases": aliases if isinstance(aliases, list) else [aliases],
                    "tags": tags if isinstance(tags, list) else [tags],
                    "links": wikilinks(body),
                    "length": len(tokens),
                    "tf": dict(counts),
                }
            )
        payload = {
            "schema_version": 1,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "fingerprints": fingerprints,
            "document_count": len(documents),
            "average_length": (
                sum(document["length"] for document in documents) / len(documents)
                if documents
                else 0.0
            ),
            "document_frequency": dict(document_frequency),
            "documents": documents,
        }
        self.paths.index_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.index_file.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.paths.index_file)
        return {
            "status": "success",
            "index_path": str(self.paths.index_file),
            "document_count": len(documents),
            "term_count": len(document_frequency),
        }

    def _load(self) -> dict[str, Any]:
        if not self.paths.index_file.exists():
            self.build()
        payload = json.loads(self.paths.index_file.read_text(encoding="utf-8"))
        if payload.get("fingerprints") != self._fingerprints():
            self.build()
            payload = json.loads(self.paths.index_file.read_text(encoding="utf-8"))
        return payload

    def search(
        self,
        query: str,
        limit: int = 8,
        page_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        payload = self._load()
        query_tokens = tokenize(query)
        if not query_tokens:
            return {"status": "success", "query": query, "results": []}
        n_docs = max(int(payload["document_count"]), 1)
        average_length = max(float(payload["average_length"]), 1.0)
        document_frequency = payload["document_frequency"]
        lower_query = query.casefold()
        results: list[dict[str, Any]] = []
        for document in payload["documents"]:
            if page_type and document.get("type") != page_type:
                continue
            if status and document.get("status") != status:
                continue
            length = max(float(document["length"]), 1.0)
            score = 0.0
            for token in query_tokens:
                frequency = float(document["tf"].get(token, 0))
                if frequency <= 0:
                    continue
                df = float(document_frequency.get(token, 0))
                inverse = math.log(1.0 + ((n_docs - df + 0.5) / (df + 0.5)))
                denominator = frequency + 1.5 * (
                    1.0 - 0.75 + 0.75 * length / average_length
                )
                score += inverse * (frequency * 2.5) / denominator
            title = str(document["title"]).casefold()
            title_tokens = set(tokenize(title))
            aliases = " ".join(map(str, document.get("aliases") or [])).casefold()
            tags = " ".join(map(str, document.get("tags") or [])).casefold()
            score += 0.8 * len(set(query_tokens) & title_tokens)
            if lower_query in title:
                score += 4.0
            if lower_query in aliases:
                score += 2.0
            if lower_query in tags:
                score += 1.0
            if document.get("status") == "validated":
                score *= 1.15
            elif document.get("status") == "case-specific":
                score *= 1.05
            elif document.get("status") == "candidate":
                score *= 0.92
            if document.get("type") == "meta":
                score *= 0.35
            if score > 0:
                results.append(
                    {
                        "path": document["path"],
                        "id": document.get("id"),
                        "title": document["title"],
                        "type": document.get("type"),
                        "status": document.get("status"),
                        "score": round(score, 6),
                        "links": document.get("links") or [],
                    }
                )
        results.sort(key=lambda item: (-item["score"], item["path"]))
        return {
            "status": "success",
            "query": query,
            "tokens": query_tokens,
            "results": results[: max(1, min(limit, 50))],
            "index_path": str(self.paths.index_file),
        }

    def context_pack(self, query: str, mode: str = "standard") -> dict[str, Any]:
        limits = {"quick": 5, "standard": 12, "deep": 25}
        limit = limits.get(mode, limits["standard"])
        search = self.search(query, limit=max(5, limit))
        selected = list(search["results"])
        if selected:
            all_pages = {
                path.stem.casefold(): path
                for path in self._page_files()
            }
            seen = {item["path"] for item in selected}
            for link in selected[0].get("links", []):
                target = all_pages.get(Path(link).stem.casefold())
                if target:
                    relative = target.relative_to(self.paths.root).as_posix()
                    if relative not in seen and len(selected) < limit:
                        metadata, _ = read_page(target)
                        selected.append(
                            {
                                "path": relative,
                                "id": metadata.get("id"),
                                "title": metadata.get("title") or target.stem,
                                "type": metadata.get("type"),
                                "status": metadata.get("status"),
                                "score": 0.0,
                                "expanded_from": search["results"][0]["path"],
                            }
                        )
                        seen.add(relative)
        pages: list[dict[str, Any]] = []
        for item in selected[:limit]:
            path = self.paths.root / item["path"]
            metadata, body = read_page(path)
            pages.append(
                {
                    **item,
                    "metadata": metadata,
                    "content": body.strip(),
                }
            )
        return {
            "status": "success",
            "query": query,
            "mode": mode,
            "page_limit": limit,
            "pages": pages,
        }
