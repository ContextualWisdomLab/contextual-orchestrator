# Contextual Orchestrator OpenAI-compatible server with the Postgres KV driver.
#
# Build:  docker build -t contextual-orchestrator .
# Run  :  seed CONTEXTUAL_ORCHESTRATOR_TOKEN and provider credentials into the KV
#        registry first, then use:
#        docker run --rm -p 8000:8000 contextual-orchestrator
# Runtime secrets are never passed through the container environment or argv;
# see docs/kv-credentials.md for the bootstrap flow.
# Agents: defaults to the bundled mock pool; mount your own and set AGENTS_FILE:
#           -v ./agents.json:/app/agents.json -e AGENTS_FILE=/app/agents.json
# Rust and maturin are build-only and pinned by an immutable multi-architecture
# image digest; the runtime remains the pinned slim Python image.
ARG MATURIN_BUILDER_IMAGE=ghcr.io/pyo3/maturin@sha256:b6c8b59a0170b77eb31a35b56034abd39972483ad0ebfff344deaa42a85f3bd3
FROM ${MATURIN_BUILDER_IMAGE} AS token-builder
COPY rust/Cargo.toml rust/Cargo.lock /build/rust/
COPY rust/token_counter/ /build/rust/token_counter/
COPY contextual_orchestrator/ /build/contextual_orchestrator/
WORKDIR /build/rust/token_counter
RUN maturin build --locked --release --out /build/wheels

# Export only the native wheel for host-based fuzz jobs. BuildKit writes this
# scratch stage to a temporary directory without a bind mount into the builder.
FROM scratch AS token-wheel
COPY --from=token-builder /build/wheels /

# python:3.12-slim
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS runtime-base
WORKDIR /app

WORKDIR /app
COPY pyproject.toml requirements.lock README.md LICENSE ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY contextual_orchestrator/ /usr/local/lib/python3.12/site-packages/contextual_orchestrator/
COPY examples/ examples/
COPY --from=token-builder /build/wheels /tmp/token-wheels
RUN pip install --no-cache-dir /tmp/token-wheels/*.whl && rm -rf /tmp/token-wheels

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
CMD ["sh", "-c", "python -m contextual_orchestrator --serve --agents \"$AGENTS_FILE\" --host 0.0.0.0 --port \"$PORT\" --allow-public-bind --auth-token-key CONTEXTUAL_ORCHESTRATOR_TOKEN"]

# Local and CI tests share this target. The wheel remains a BuildKit artifact:
# it is installed only into uv's ephemeral, hash-locked Python 3.12 environment.
FROM runtime-base AS test-runner
USER root
COPY --from=token-builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=token-builder /build/wheels /tmp/token-wheels
COPY . /io
WORKDIR /io
RUN set -eu; \
    set -- /tmp/token-wheels/*.whl; \
    test "$#" -eq 1 && test -f "$1" || { \
      echo "pinned Rust token-packer build must produce exactly one wheel" >&2; exit 1; \
    }; \
    uv run --python /usr/local/bin/python --no-project \
      --with-requirements requirements.lock \
      --with-requirements fuzz/requirements-property.txt \
      --with "$1" python -m pytest -q
USER orchestrator

FROM runtime-base AS runtime
