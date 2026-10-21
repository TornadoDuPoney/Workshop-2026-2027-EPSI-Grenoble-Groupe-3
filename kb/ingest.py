"""
Ingestion de la base de connaissances vers Qdrant — RESILIENCE-ALPHA.

Lit les documents Markdown de ce dossier, les découpe en passages, calcule
leurs embeddings avec le modèle local (Ollama), et les stocke dans Qdrant.
Le moteur de remédiation interroge ensuite cette base (RAG) pour ancrer son
analyse sur la documentation réelle de l'infrastructure.

Usage (dans un conteneur qui voit ollama et qdrant) :
    python ingest.py

Prérequis : le modèle d'embedding doit être présent dans Ollama :
    docker exec resilience-ollama ollama pull nomic-embed-text
"""
import glob
import os
import uuid

import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.getenv("KB_COLLECTION", "infra")
KB_DIR = os.getenv("KB_DIR", os.path.dirname(os.path.abspath(__file__)))


def chunk_markdown(text: str, source: str) -> list[dict]:
    """Découpe un document par sections (titres ##), passages non vides."""
    chunks = []
    current_title = source
    buffer: list[str] = []

    def flush():
        if buffer:
            body = "\n".join(buffer).strip()
            if body:
                chunks.append({"source": source, "title": current_title, "text": f"{current_title}\n{body}"})

    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("# "):
            flush()
            buffer = []
            current_title = line.lstrip("# ").strip()
        else:
            buffer.append(line)
    flush()
    return chunks


def embed(text: str) -> list[float]:
    """Embedding d'un texte via le modèle local Ollama."""
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["embedding"]


def main():
    files = sorted(glob.glob(os.path.join(KB_DIR, "*.md")))
    print(f"[ingest] {len(files)} documents trouvés dans {KB_DIR}")

    all_chunks = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            all_chunks.extend(chunk_markdown(f.read(), os.path.basename(path)))
    print(f"[ingest] {len(all_chunks)} passages à indexer")

    # Dimension du vecteur déterminée par le premier embedding.
    first_vec = embed(all_chunks[0]["text"])
    dim = len(first_vec)

    client = QdrantClient(url=QDRANT_URL)
    client.recreate_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    points = []
    for i, ch in enumerate(all_chunks):
        vec = first_vec if i == 0 else embed(ch["text"])
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload={"source": ch["source"], "title": ch["title"], "text": ch["text"]},
        ))
        print(f"[ingest]   indexé {i + 1}/{len(all_chunks)} — {ch['source']} / {ch['title']}")

    client.upsert(collection_name=COLLECTION, points=points)
    print(f"[ingest] terminé : {len(points)} passages dans la collection '{COLLECTION}'")


if __name__ == "__main__":
    main()
