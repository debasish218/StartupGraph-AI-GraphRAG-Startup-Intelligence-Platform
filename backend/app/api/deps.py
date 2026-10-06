import secrets

from fastapi import Header, HTTPException, Request, status

from app.agents.entities import TOPICS
from app.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


def topic_terms(topic: str | None) -> list[str]:
    if not topic:
        return []
    return TOPICS.get(topic, [topic.lower()])


def require_admin(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Protect ingestion endpoints. Open in development when ADMIN_API_KEY is unset."""
    settings = request.app.state.container.settings
    expected = settings.admin_api_key
    if not expected:
        if settings.environment == "production":
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ADMIN_API_KEY is not configured")
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing X-API-Key")
