from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import get_settings


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    provider: str
    model: str
    status: str
    error: str = ""


class RepositoryEmbeddingService:
    """Production embedding boundary for repository code chunks.

    Production uses Vertex/Gemini embeddings. Local development and tests can use
    the deterministic keyword embedding path so the app remains runnable without
    cloud credentials.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def embed_texts(self, texts: list[str], *, local_keywords: list[list[str]] | None = None) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(vectors=[], provider=self.settings.repo_embedding_provider, model=self.settings.repo_embedding_model, status="empty")

        if self.settings.repo_embedding_provider == "vertex":
            try:
                vectors = self._vertex_embeddings(texts)
                return EmbeddingBatch(vectors=vectors, provider="vertex", model=self.settings.repo_embedding_model, status="ready")
            except Exception as exc:
                if not self.settings.repo_embedding_fallback_to_local:
                    return EmbeddingBatch(
                        vectors=[[] for _ in texts],
                        provider="vertex",
                        model=self.settings.repo_embedding_model,
                        status="failed",
                        error=str(exc)[:1000],
                    )
                fallback = self._local_embeddings(texts, local_keywords=local_keywords)
                return EmbeddingBatch(
                    vectors=fallback,
                    provider="local_fallback",
                    model=f"local-keyword-v1-after-{self.settings.repo_embedding_model}",
                    status="fallback",
                    error=str(exc)[:1000],
                )

        vectors = self._local_embeddings(texts, local_keywords=local_keywords)
        return EmbeddingBatch(vectors=vectors, provider="local", model="local-keyword-v1", status="ready")

    def _vertex_embeddings(self, texts: list[str]) -> list[list[float]]:
        from google import genai
        from google.genai import types

        client = genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=self.settings.google_cloud_location,
        )
        response = client.models.embed_content(
            model=self.settings.repo_embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self.settings.repo_embedding_dimensions),
        )
        embeddings = getattr(response, "embeddings", None) or []
        vectors = [_normalize_vector(list(getattr(item, "values", None) or [])) for item in embeddings]
        if len(vectors) != len(texts):
            raise RuntimeError(f"Vertex returned {len(vectors)} embedding(s) for {len(texts)} text chunk(s)")
        if any(not vector for vector in vectors):
            raise RuntimeError("Vertex returned an empty embedding vector")
        return vectors

    def _local_embeddings(self, texts: list[str], *, local_keywords: list[list[str]] | None) -> list[list[float]]:
        from app.services.repo_context import extract_keywords, keyword_embedding

        vectors = []
        for index, text in enumerate(texts):
            keywords = local_keywords[index] if local_keywords and index < len(local_keywords) else extract_keywords(text)
            vectors.append(keyword_embedding(keywords, dimensions=max(1, self.settings.repo_embedding_dimensions)))
        return vectors


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _normalize_vector(vector: list[float]) -> list[float]:
    magnitude = sum(value * value for value in vector) ** 0.5
    if not magnitude:
        return vector
    return [round(value / magnitude, 8) for value in vector]
