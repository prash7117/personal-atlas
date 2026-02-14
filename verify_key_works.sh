# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

python - <<'PY'
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=".env")  # <-- explicit path

key = os.getenv("OPENAI_API_KEY", "")
print("key_len:", len(key), "prefix:", key[:3])

client = OpenAI(api_key=key)
resp = client.embeddings.create(
    model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
    input=["hello world"],
)

print("OK — embedding size:", len(resp.data[0].embedding))
PY

