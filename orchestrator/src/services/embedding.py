"""Vertex AI embedding client using Google GenAI SDK.

Calls text-embedding-004 model. No local model, no cold start.
768-dimensional embeddings.
"""
from __future__ import annotations
import os

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "noospheric-orrery")
        region = os.environ.get("VERTEX_AI_REGION", "us-central1")
        _client = genai.Client(vertexai=True, project=project_id, location=region)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using Vertex AI text-embedding-004.

    Returns list of 768-dimensional embedding vectors.
    """
    if not texts:
        return []

    client = _get_client()
    result = client.models.embed_content(
        model="text-embedding-004",
        contents=texts,
    )
    return [e.values for e in result.embeddings]


def embed_text(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]


def get_embedding_dimension() -> int:
    """Return the dimensionality of the embedding model."""
    return 768
