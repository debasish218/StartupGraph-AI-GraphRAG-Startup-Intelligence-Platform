"""LLM and embedding provider abstraction.

Every agent works without an LLM (rule-based fallback). When ``LLM_PROVIDER`` is
set, agents use the chat model for classification, extraction, Cypher generation
and answer synthesis, and fall back to the rules if a call fails.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache
from typing import Any, Protocol

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

DEFAULT_CHAT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-sonnet-5-5",
}

DEFAULT_EMBEDDING_MODELS = {
    "local": "sentence-transformers/all-MiniLM-L6-v2",
    "openai": "text-embedding-3-small",
    "gemini": "models/text-embedding-004",
}


@lru_cache
def get_chat_model() -> Any | None:
    """Return a LangChain chat model, or None when running rule-based."""
    s = get_settings()
    if s.llm_provider == "none":
        return None
    model = s.llm_model or DEFAULT_CHAT_MODELS[s.llm_provider]
    try:
        if s.llm_provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=model, temperature=s.llm_temperature, api_key=s.openai_api_key)
        if s.llm_provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model, temperature=s.llm_temperature, google_api_key=s.google_api_key
            )
        if s.llm_provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(model=model, temperature=s.llm_temperature, api_key=s.anthropic_api_key)
    except Exception:  # pragma: no cover - misconfiguration path
        log.exception("Could not initialise LLM provider %s; using rule-based agents", s.llm_provider)
    return None


class Embedder(Protocol):
    dim: int
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic feature-hashing embedder (bag of words + bigrams).

    Not semantic in the neural sense, but keyword-overlap aware. Used in tests/CI
    and as a fallback when no model is available.
    """

    name = "hash"

    def __init__(self, dim: int):
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for feat in features:
            h = int.from_bytes(hashlib.md5(feat.encode()).digest()[:8], "little")
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class LangChainEmbedder:
    def __init__(self, impl: Any, dim: int, name: str):
        self._impl = impl
        self.dim = dim
        self.name = name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._impl.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._impl.embed_query(text)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = get_dim()
        self.name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def build_embedder(s: Settings) -> Embedder:
    model = s.embedding_model or DEFAULT_EMBEDDING_MODELS.get(s.embedding_provider, "")
    try:
        if s.embedding_provider == "local":
            emb = SentenceTransformerEmbedder(model)
        elif s.embedding_provider == "openai":
            from langchain_openai import OpenAIEmbeddings

            emb = LangChainEmbedder(
                OpenAIEmbeddings(model=model, api_key=s.openai_api_key, dimensions=s.embedding_dim),
                s.embedding_dim,
                model,
            )
        elif s.embedding_provider == "gemini":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            emb = LangChainEmbedder(
                GoogleGenerativeAIEmbeddings(model=model, google_api_key=s.google_api_key),
                s.embedding_dim,
                model,
            )
        else:
            return HashEmbedder(s.embedding_dim)
    except Exception as exc:
        log.warning("Embedding provider %s unavailable (%s); using hash embedder", s.embedding_provider, exc)
        return HashEmbedder(s.embedding_dim)

    if emb.dim != s.embedding_dim:
        raise ValueError(
            f"Embedding model {model} produces {emb.dim}-d vectors but EMBEDDING_DIM={s.embedding_dim}. "
            "Set EMBEDDING_DIM to match (the pgvector column is created with that size)."
        )
    return emb


@lru_cache
def get_embedder() -> Embedder:
    return build_embedder(get_settings())
