#!/usr/bin/env sh
set -eu

export UV_CACHE_DIR="${UV_CACHE_DIR:-.local/uv-cache}"
mkdir -p "$UV_CACHE_DIR"

if [ -n "${SERVER_PORT:-}" ] && [ -z "${WEB_PORT:-}" ]; then
  export WEB_PORT="$SERVER_PORT"
fi

if [ -n "${PORT:-}" ] && [ -z "${WEB_PORT:-}" ]; then
  export WEB_PORT="$PORT"
fi

exec uv run python main.py
