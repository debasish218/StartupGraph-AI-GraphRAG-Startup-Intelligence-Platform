"""Application settings, loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "StartupGraph AI"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    admin_api_key: str = ""  # required for /api/ingest/* in production

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "startupgraph"
    neo4j_database: str = "neo4j"

    # PostgreSQL + pgvector
    postgres_dsn: str = "postgresql://startupgraph:startupgraph@localhost:5432/startupgraph"

    # LLM: "none" runs the deterministic rule-based agents (no API key needed).
    llm_provider: Literal["none", "openai", "gemini", "anthropic"] = "none"
    llm_model: str = ""  # empty -> provider default
    llm_temperature: float = 0.0
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""

    # Embeddings: "hash" is a dependency-free fallback suitable for tests/CI only.
    embedding_provider: Literal["local", "openai", "gemini", "hash"] = "local"
    embedding_model: str = ""  # empty -> provider default
    embedding_dim: int = 384

    # Retrieval
    vector_top_k: int = 6
    graph_result_limit: int = 50
    cypher_timeout_s: float = 10.0

    # Ingestion
    rss_feeds: str = (
        "https://techcrunch.com/category/startups/feed/,"
        "https://techcrunch.com/category/artificial-intelligence/feed/,"
        "https://techcrunch.com/category/venture/feed/"
    )
    rss_poll_minutes: int = 0  # 0 disables the background poller
    yc_directory_url: str = "https://yc-oss.github.io/api/companies/all.json"
    github_token: str = ""
    seed_on_startup: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def rss_feed_list(self) -> list[str]:
        return [f.strip() for f in self.rss_feeds.split(",") if f.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
