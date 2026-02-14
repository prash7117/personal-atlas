# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

import os
import sys
from types import SimpleNamespace
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from openai import OpenAI

load_dotenv(dotenv_path=".env")

QDRANT_URL = os.environ["QDRANT_URL"]
COLLECTION = os.environ["QDRANT_COLLECTION"]
EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")


def _fetch_payloads(qdrant: QdrantClient, ids, batch_size: int = 4):
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


def main(question: str, top_k: int = 5):
    qdrant = QdrantClient(url=QDRANT_URL)
    oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    qvec = oai.embeddings.create(model=EMBED_MODEL, input=[question]).data[0].embedding

    # qdrant-client 1.16+: query_points()
    if hasattr(qdrant, "query_points"):
        res = qdrant.query_points(
            collection_name=COLLECTION,
            query=qvec,
            limit=top_k,
            with_payload=False,
            with_vectors=False,
        )
        hits = res.points or []
        ids = [
            getattr(h, "id", None) for h in hits if getattr(h, "id", None) is not None
        ]
        payloads = _fetch_payloads(qdrant, ids)
        hits = [
            SimpleNamespace(
                id=getattr(h, "id", None),
                score=getattr(h, "score", None),
                payload=payloads.get(getattr(h, "id", None)),
            )
            for h in hits
        ]
        get_score = lambda h: getattr(h, "score", None)
        get_payload = lambda h: getattr(h, "payload", None)
    else:
        # older clients: search()
        hits = qdrant.search(
            collection_name=COLLECTION,
            query_vector=qvec,
            limit=top_k,
            with_payload=False,
        )
        ids = [
            getattr(h, "id", None) for h in hits if getattr(h, "id", None) is not None
        ]
        payloads = _fetch_payloads(qdrant, ids)
        hits = [
            SimpleNamespace(
                id=getattr(h, "id", None),
                score=getattr(h, "score", None),
                payload=payloads.get(getattr(h, "id", None)),
            )
            for h in hits
        ]
        get_score = lambda h: getattr(h, "score", None)
        get_payload = lambda h: getattr(h, "payload", None)

    for i, h in enumerate(hits, 1):
        p = get_payload(h) or {}
        score = get_score(h)
        print(
            f"\n--- HIT {i} score={score:.4f} ---"
            if score is not None
            else f"\n--- HIT {i} ---"
        )
        print("path:", p.get("path"))
        print("chunk:", p.get("chunk_id"))
        print((p.get("text") or "")[:800])


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print('Usage: python query.py "your question here"')
        raise SystemExit(2)
    main(sys.argv[1])
