FROM node:22-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.8.22 AS uv
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /opt/aiqa
COPY pyproject.toml uv.lock README.md ./
COPY aiqa ./aiqa
COPY schemas ./schemas
RUN uv sync --frozen --no-dev \
    && npm install -g @anthropic-ai/claude-code@2.1.285 @playwright/mcp@0.0.83 \
    && PW_CORE="$(npm root -g)/@playwright/mcp/node_modules/playwright-core/cli.js" \
    && test -f "$PW_CORE" \
    && node "$PW_CORE" install-deps chromium \
    && playwright-mcp install-browser chrome-for-testing \
    && .venv/bin/playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 aiqa \
    && mkdir -p /runs /home/aiqa/.cache \
    && mv /root/.cache/ms-playwright /home/aiqa/.cache/ms-playwright \
    && chown -R aiqa:aiqa /runs /home/aiqa
ENV AIQA_AGENT_BROWSER=chromium
ENV PATH="/opt/aiqa/.venv/bin:${PATH}"
USER aiqa
WORKDIR /home/aiqa
CMD ["sleep", "infinity"]
