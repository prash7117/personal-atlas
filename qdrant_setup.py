# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

QDRANT_URL = "http://localhost:6333"
COLLECTION = "my_rag"
VECTOR_SIZE = 1536  # change later if your embedding model uses a different dim

client = QdrantClient(url=QDRANT_URL)

if not client.collection_exists(COLLECTION):
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )

print("OK:", client.get_collections())
