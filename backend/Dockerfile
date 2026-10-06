FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# Set INSTALL_ML=false for a slim image that uses API (OpenAI/Gemini) embeddings only.
ARG INSTALL_ML=true
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_ML" = "true" ]; then \
      pip install --index-url https://download.pytorch.org/whl/cpu torch \
      && pip install -r requirements-ml.txt \
      && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"; \
    fi

COPY app ./app
COPY data ./data

RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"

# One worker per container: startup seeding and the RSS poller run in-process. Scale with replicas.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
