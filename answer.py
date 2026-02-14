# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

import re
import fnmatch
import difflib
from types import SimpleNamespace
from typing import List, Optional
import os
import sys
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from openai import OpenAI
import json


load_dotenv(dotenv_path=".env")

QDRANT_URL = os.environ["QDRANT_URL"]
COLLECTION = os.environ["QDRANT_COLLECTION"]
EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4.1-mini")


STATE_FILE = ".rag_ingest_state.json"


def list_repo_ids_from_state(collection: str) -> List[str]:
    """
    Reads repo_ids from your ingestion state file.
    Keys look like: "<collection>::<repo_id>" and values include {"repo_id": "..."}.
    """
    try:
        from pathlib import Path

        state = json.loads(Path(STATE_FILE).read_text())
    except Exception:
        return []

    repo_ids: List[str] = []
    for k, v in state.items():
        if not isinstance(k, str) or not k.startswith(collection + "::"):
            continue
        if isinstance(v, dict) and v.get("repo_id"):
            repo_ids.append(str(v["repo_id"]))

    # de-dup while preserving order
    seen = set()
    out: List[str] = []
    for r in repo_ids:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def resolve_repo_ids(repo_id_arg: Optional[str], collection: str) -> List[str]:
    """
    Supports:
      - exact: "accentfs"
      - glob:  "acc*"
      - regex: "re:^acc(ent)?"
      - typos: close match via difflib
    Returns list of matching repo_ids. Empty list means "no match".
    """
    if not repo_id_arg:
        return []

    known = list_repo_ids_from_state(collection)
    if not known:
        # If no state exists yet, fall back to exact behavior.
        return [repo_id_arg]

    # Regex mode: re:<pattern>
    if repo_id_arg.startswith("re:"):
        pat = repo_id_arg[3:]
        try:
            rx = re.compile(pat)
        except re.error:
            return []
        return [r for r in known if rx.search(r)]

    # Glob mode: acc*, foo?, [ab]*
    if any(ch in repo_id_arg for ch in ["*", "?", "["]):
        return [r for r in known if fnmatch.fnmatch(r, repo_id_arg)]

    # Exact
    if repo_id_arg in known:
        return [repo_id_arg]

    # Fuzzy suggestions
    sugg = difflib.get_close_matches(repo_id_arg, known, n=5, cutoff=0.6)
    if sugg:
        return [sugg[0]]

    return []


def make_filter(repo_ids: List[str]):
    must = []
    if repo_ids:
        # OR across multiple repo_ids: should=[repo_id==A, repo_id==B, ...]
        should = [
            FieldCondition(key="repo_id", match=MatchValue(value=r)) for r in repo_ids
        ]
        return Filter(must=must, should=should)

    return Filter(must=must) if must else None


def _fetch_payloads(qdrant: QdrantClient, ids: List, batch_size: int = 4):
    payloads = {}
    if not ids or not hasattr(qdrant, "retrieve"):
        return payloads

    def _retrieve(batch):
        return qdrant.retrieve(
            collection_name=COLLECTION,
            ids=batch,
            with_payload=True,
            with_vectors=False,
        )

    for i in range(0, len(ids), batch_size):
        batch = ids[i : i + batch_size]
        try:
            records = _retrieve(batch)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(
                f"Warning: qdrant retrieve failed for batch of {len(batch)} ids: {exc}",
                file=sys.stderr,
            )
            # Try per-id to isolate corrupt points and keep the rest.
            for single_id in batch:
                try:
                    records = _retrieve([single_id])
                except Exception as exc2:  # pylint: disable=broad-exception-caught
                    print(
                        f"Warning: skipping point id {single_id}: {exc2}",
                        file=sys.stderr,
                    )
                    continue
                for r in records:
                    payloads[getattr(r, "id", None)] = getattr(r, "payload", None)
            continue

        for r in records:
            payloads[getattr(r, "id", None)] = getattr(r, "payload", None)
    return payloads


def _search_points(qdrant: QdrantClient, query_vec, limit: int):
    # Avoid server-side payload filters to sidestep payload index corruption.
    res = qdrant.query_points(
        collection_name=COLLECTION,
        query=query_vec,
        limit=limit,
        with_payload=False,
        with_vectors=False,
        query_filter=None,
    )
    points = res.points or []
    ids = [getattr(p, "id", None) for p in points if getattr(p, "id", None) is not None]
    payloads = _fetch_payloads(qdrant, ids)

    hydrated = []
    for p in points:
        pid = getattr(p, "id", None)
        hydrated.append(
            SimpleNamespace(
                id=pid,
                score=getattr(p, "score", None),
                payload=payloads.get(pid),
            )
        )
    return hydrated


def retrieve(qdrant: QdrantClient, query_vec, top_k: int, repo_ids: List[str]):
    if not repo_ids:
        return _search_points(qdrant, query_vec, top_k)

    max_limit = 200
    limits = []
    for mult in (5, 10, 20):
        limit = min(max(top_k * mult, top_k), max_limit)
        if limit not in limits:
            limits.append(limit)
    if not limits:
        limits = [top_k]

    filtered: List[SimpleNamespace] = []
    for limit in limits:
        points = _search_points(qdrant, query_vec, limit)
        filtered = [p for p in points if (p.payload or {}).get("repo_id") in repo_ids]
        if len(filtered) >= top_k or limit == limits[-1]:
            break

    return filtered[:top_k]


def build_context(points, max_chars: int = 12000):
    parts = []
    used = 0
    for p in points:
        payload = p.payload or {}

        path = payload.get("path", "unknown")
        chunk_id = payload.get("chunk_id", "NA")
        text = (payload.get("text") or "").strip()
        if not text:
            continue

        block = f"\n\n### Source: {path} (chunk {chunk_id})\n{text}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def answer(
    question: str,
    repo_id_args: Optional[List[str]],
    top_k: int,
    max_ctx_chars: int,
    show_sources: bool,
):
    qdrant = QdrantClient(url=QDRANT_URL)
    oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    qvec = oai.embeddings.create(model=EMBED_MODEL, input=[question]).data[0].embedding
    repo_ids: List[str] = []
    repo_id_misses: List[str] = []
    if repo_id_args:
        seen = set()
        for repo_id_arg in repo_id_args:
            if repo_id_arg is None:
                continue
            value = str(repo_id_arg).strip()
            if not value:
                continue
            matches = resolve_repo_ids(value, COLLECTION)
            if not matches:
                repo_id_misses.append(value)
                continue
            for match in matches:
                if match not in seen:
                    seen.add(match)
                    repo_ids.append(match)

    if repo_id_args and repo_id_misses:
        if repo_ids:
            msg = "Ignoring repo-id patterns with no match: " + ", ".join(
                repo_id_misses
            )
        else:
            msg = "No repo-id patterns matched. Searching across all repos."
        print(msg, file=sys.stderr)

    points = retrieve(qdrant, qvec, top_k=top_k, repo_ids=repo_ids)

    context = build_context(points, max_chars=max_ctx_chars)

    if show_sources:
        print("=== RETRIEVED SOURCES (truncated) ===")
        shown = 0
        for p in points:
            payload = p.payload or {}
            relpath = payload.get("relpath") or payload.get("path")
            chunk_id = payload.get("chunk_id")
            if relpath is None or chunk_id is None:
                continue
            shown += 1
            print(
                f"{shown}. {relpath}  chunk={chunk_id}  score={getattr(p, 'score', None)}"
            )
        print("=== END SOURCES ===\n")

    system = (
        "You are a software engineering assistant.\n"
        "Answer ONLY using the provided sources.\n"
        "If sources are insufficient, say exactly what is missing.\n"
        "Format the response in GitHub-flavored Markdown with clear section headings "
        "(use ## / ###), bold key labels, and bullet lists where helpful.\n"
        "Use fenced code blocks with language tags for any code.\n"
        "When including URLs, write the full URL (no Markdown link syntax) so the UI can linkify.\n"
        "Cite sources using EXACTLY this format: [path=<...> chunk=<N>].\n"
        "Put citations at the end under a heading 'Citations:' with one citation per line.\n"
        "Do not invent file names, APIs, or behavior not present in sources.\n"
    )

    user = f"Question:\n{question}\n\n---\nSOURCES (verbatim):{context}\n---"

    resp = oai.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )

    print(resp.choices[0].message.content.strip())


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("question", help="question to ask")
    ap.add_argument(
        "--repo-id",
        action="append",
        default=None,
        help="restrict retrieval (repeatable): exact (accentfs), glob (acc*), regex (re:^acc), or typo",
    )
    ap.add_argument("--top-k", type=int, default=10, help="how many chunks to retrieve")
    ap.add_argument(
        "--max-ctx-chars", type=int, default=12000, help="context char budget"
    )
    ap.add_argument(
        "--show-sources", action="store_true", help="print which chunks were retrieved"
    )
    args = ap.parse_args()

    answer(
        question=args.question,
        repo_id_args=args.repo_id,
        top_k=args.top_k,
        max_ctx_chars=args.max_ctx_chars,
        show_sources=args.show_sources,
    )
