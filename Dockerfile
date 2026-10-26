# syntax=docker/dockerfile:1
# librus-mcp container: stdio by default, or self-hosted HTTP with
# `--transport http` and a bearer token, listening on every container
# interface (LIBRUS_MCP_HOST). See README.md.

ARG PYTHON_IMAGE=python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8

FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

# Release builds pass the verified wheel with `--build-context verified=dist`;
# source builds (local, Glama) leave this stage empty and install the checkout.
FROM scratch AS verified

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/librus-mcp
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
# Dependencies come from uv.lock with hashes, as in every other channel.
RUN uv sync --locked --no-dev --no-install-project
COPY src/librus_mcp ./src/librus_mcp
RUN --mount=from=verified,target=/verified \
    set -eu; \
    wheels=$(find /verified -maxdepth 1 -name 'librus_mcp-*.whl'); \
    if [ -n "$wheels" ]; then \
        uv pip install --python /opt/librus-mcp/bin/python --no-deps $wheels; \
    else \
        uv sync --locked --no-dev --no-editable; \
    fi

FROM ${PYTHON_IMAGE}
LABEL io.modelcontextprotocol.server.name="io.github.krzysztofbury/librus-mcp" \
      org.opencontainers.image.title="librus-mcp" \
      org.opencontainers.image.description="MCP server for the Librus Synergia school gradebook" \
      org.opencontainers.image.source="https://github.com/krzysztofbury/librus-mcp" \
      org.opencontainers.image.licenses="MIT"
# A fixed unprivileged user owns /data, so an empty named volume inherits the
# ownership and the server can keep its private state there.
RUN groupadd --system --gid 10001 librus \
    && useradd --system --uid 10001 --gid librus --home-dir /data --no-create-home librus \
    && mkdir -p /data/state /data/downloads \
    && chown -R 10001:10001 /data \
    && chmod -R 700 /data
COPY --from=build /opt/librus-mcp /opt/librus-mcp
ENV PATH=/opt/librus-mcp/bin:$PATH \
    HOME=/data \
    LIBRUS_STATE_DIR=/data/state \
    LIBRUS_DOWNLOAD_DIR=/data/downloads \
    LIBRUS_MCP_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /data
EXPOSE 8000
ENTRYPOINT ["librus-mcp"]
