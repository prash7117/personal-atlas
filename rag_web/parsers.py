# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

"""Parsers for answer.py stdout."""

import re
from typing import Dict, List


SOURCE_START_RE = re.compile(r"^=== RETRIEVED SOURCES.*===$", re.M)
SOURCE_END_RE = re.compile(r"^=== END SOURCES ===$", re.M)
SOURCE_LINE_RE = re.compile(
    r"^\s*\d+\.\s+(?P<path>.+?)\s+chunk=(?P<chunk>\d+)\s+score=(?P<score>[^\s]+)\s*$"
)
CITATION_RE = re.compile(r"^\s*\[\s*path=(?P<path>.+?)\s+chunk=(?P<chunk>\d+)\s*\]\s*$")


def _parse_sources(text: str) -> List[Dict]:
    """Parse retrieved sources block from stdout."""
    sources: List[Dict] = []
    for line in text.splitlines():
        match = SOURCE_LINE_RE.match(line.strip())
        if not match:
            continue
        path = match.group("path")
        chunk = int(match.group("chunk"))
        score_raw = match.group("score")
        try:
            score = float(score_raw)
        except Exception:  # pylint: disable=broad-exception-caught
            score = None
        sources.append(
            {
                "path": path,
                "chunk": chunk,
                "score": score,
                "text_preview": "",
            }
        )
    return sources


def _parse_citations(text: str) -> List[Dict]:
    """Parse citation lines from stdout."""
    citations: List[Dict] = []
    for line in text.splitlines():
        match = CITATION_RE.match(line.strip())
        if not match:
            continue
        citations.append(
            {
                "path": match.group("path"),
                "chunk": int(match.group("chunk")),
            }
        )
    return citations


def parse_answer_output(stdout: str) -> Dict:
    """Parse answer.py stdout into answer, sources, and citations."""
    result = {
        "answer": "",
        "sources": [],
        "citations": [],
        "raw_stdout": stdout,
    }

    if not stdout.strip():
        return result

    answer_text = stdout.strip()
    sources_text = ""

    start_match = SOURCE_START_RE.search(stdout)
    end_match = SOURCE_END_RE.search(stdout)
    if start_match and end_match and end_match.start() > start_match.end():
        sources_text = stdout[start_match.end() : end_match.start()]
        answer_text = stdout[end_match.end() :].strip()

    if sources_text:
        result["sources"] = _parse_sources(sources_text)

    if "Citations:" in answer_text:
        parts = answer_text.split("Citations:", 1)
        answer_body = parts[0].strip()
        citations_text = parts[1]
        result["citations"] = _parse_citations(citations_text)
        result["answer"] = answer_body
    else:
        result["citations"] = _parse_citations(answer_text)
        result["answer"] = answer_text

    return result
