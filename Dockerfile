# Contextual Orchestrator OpenAI-compatible server with the Postgres KV driver.
#
# Build:  docker build -t contextual-orchestrator .
# Run  :  seed CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN,
#        CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN, and provider credentials into the KV
#        registry first, then use:
#        docker run --rm -p 8000:8000 contextual-orchestrator
# Runtime secrets are never passed through the container environment or argv;
# see docs/kv-credentials.md for the bootstrap flow.
# Agents: defaults to the bundled mock pool; mount your own and set AGENTS_FILE:
#           -v ./agents.json:/app/agents.json -e AGENTS_FILE=/app/agents.json
ARG MATURIN_BUILDER_IMAGE=ghcr.io/pyo3/maturin@sha256:b6c8b59a0170b77eb31a35b56034abd39972483ad0ebfff344deaa42a85f3bd3
FROM ${MATURIN_BUILDER_IMAGE} AS maturin-tools
FROM rust:1.97.1-slim-bookworm@sha256:2775a09d208ff0d7c1f50490c45b62db929e87ba1dcbc3f2132ac71a704bcdd3 AS dependency-builder
RUN apt-get update \
    && apt-get install --no-install-recommends --yes build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY --from=maturin-tools /usr/local/bin/uv /usr/local/bin/uv
COPY --from=maturin-tools /usr/bin/maturin /usr/local/bin/maturin
COPY requirements.lock /build/requirements.lock
COPY rust/Cargo.toml rust/Cargo.lock /build/rust/
COPY rust/token_counter/ /build/rust/token_counter/
COPY contextual_orchestrator/ /build/contextual_orchestrator/
RUN uv python install 3.12 \
    && uv pip install --python 3.12 --require-hashes -r /build/requirements.lock --target /build/deps \
    && maturin build --locked --release --manifest-path /build/rust/token_counter/Cargo.toml --out /build/wheels \
    && uv pip install --python 3.12 /build/wheels/*.whl --target /build/deps

# python:3.12-slim
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

WORKDIR /app
COPY pyproject.toml requirements.lock README.md LICENSE ./
COPY --from=dependency-builder /build/deps/ /usr/local/lib/python3.12/site-packages/
COPY contextual_orchestrator/ /usr/local/lib/python3.12/site-packages/contextual_orchestrator/
COPY examples/ examples/

ENV AGENTS_FILE=/app/examples/agents.mock.json \
    PORT=8000

RUN useradd --uid 10001 --create-home orchestrator \
    && mkdir -p /var/lib/contextual-orchestrator \
    && chown -R orchestrator:orchestrator /var/lib/contextual-orchestrator
USER orchestrator

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD ["python", "-c", "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz', timeout=2)"]

# --allow-public-bind: 컨테이너 내부 0.0.0.0 바인딩 필요(외부 노출은 호스트 포트 매핑이 결정)
CMD ["sh", "-c", "python -m contextual_orchestrator --serve --agents \"$AGENTS_FILE\" --host 0.0.0.0 --port \"$PORT\" --allow-public-bind --production --admin-token-key CONTEXTUAL_ORCHESTRATOR_ADMIN_TOKEN --inference-token-key CONTEXTUAL_ORCHESTRATOR_INFERENCE_TOKEN"]
