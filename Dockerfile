# 5e Lite art is CC0, so the image carries it. The fetch needs only pngjs; npm ci would also pull
# the 5e-database archive.
FROM node:22-bookworm-slim AS lite5e-art
WORKDIR /lite5e
COPY src/rulehall/engines/lite5e/srd/package.json pins.json
COPY src/rulehall/engines/lite5e/srd/fetch-assets.js src/rulehall/engines/lite5e/srd/source.js srd/
COPY src/rulehall/engines/lite5e/srd/overlay/art.json srd/overlay/
COPY src/rulehall/engines/lite5e/data/character_options.json \
     src/rulehall/engines/lite5e/data/bestiary.json \
     data/
RUN npm --prefix srd install --no-save "pngjs@$(node -p 'require("./pins.json").dependencies.pngjs')" \
    && node srd/fetch-assets.js

FROM node:22-bookworm-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON=3.13 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

COPY src/rulehall/engines/pokemon/showdown/package.json \
     src/rulehall/engines/pokemon/showdown/package-lock.json \
     src/rulehall/engines/pokemon/showdown/
RUN npm --prefix src/rulehall/engines/pokemon/showdown ci --omit=optional && npm cache clean --force

ARG CLAUDE_CLI_WEEK
RUN npm install -g @anthropic-ai/claude-code @openai/codex && npm cache clean --force

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-default-groups --no-install-project

COPY scenarios scenarios
COPY characters characters
COPY src src
COPY --from=lite5e-art /lite5e/assets src/rulehall/engines/lite5e/assets
RUN uv sync --locked --no-default-groups

# A file, not an env var: a NAS update copies the old container env onto the new image.
ARG RULEHALL_VERSION=dev
RUN echo "$RULEHALL_VERSION" > src/rulehall/app/VERSION

RUN mkdir -m 1777 /home/rulehall /data && ln -s /data/vendor /app/vendor
ENV SERVER__HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/rulehall

WORKDIR /data
EXPOSE 8080
HEALTHCHECK --interval=30s --start-period=30s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/status', timeout=5)"]
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/rulehall-entrypoint
ENTRYPOINT ["rulehall-entrypoint"]
CMD ["rulehall"]
