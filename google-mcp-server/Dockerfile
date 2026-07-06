FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-managed \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PORT=8000
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "google_mcp_server"]
