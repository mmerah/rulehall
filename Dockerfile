FROM node:25-bookworm-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON=3.13 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

COPY src/rulehall/engines/pokemon/dex.json src/rulehall/engines/pokemon/avatars.json src/rulehall/engines/pokemon/
COPY src/rulehall/engines/pokemon/showdown/package.json \
     src/rulehall/engines/pokemon/showdown/package-lock.json \
     src/rulehall/engines/pokemon/showdown/fetch-assets.js \
     src/rulehall/engines/pokemon/showdown/net.js \
     src/rulehall/engines/pokemon/showdown/
RUN npm --prefix src/rulehall/engines/pokemon/showdown run setup && npm cache clean --force

ARG CLAUDE_CLI_WEEK
RUN npm install -g @anthropic-ai/claude-code @openai/codex && npm cache clean --force

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-default-groups --no-install-project

COPY scenarios scenarios
COPY characters characters
COPY src src
RUN uv sync --locked --no-default-groups

RUN mkdir -m 1777 /home/rulehall /data
ENV SERVER__HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/rulehall

WORKDIR /data
EXPOSE 8080
HEALTHCHECK --interval=30s --start-period=30s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/status', timeout=5)"]
CMD ["rulehall"]
