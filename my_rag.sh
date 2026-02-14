# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

python - <<'PY'
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

load_dotenv(dotenv_path=".env")

url = os.environ["QDRANT_URL"]
collection = os.environ["QDRANT_COLLECTION"]

client = QdrantClient(url=url)

if client.collection_exists(collection):
    client.delete_collection(collection_name=collection)

client.create_collection(
    collection_name=collection,
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
)

print("Recreated (non-deprecated):", collection)
PY

