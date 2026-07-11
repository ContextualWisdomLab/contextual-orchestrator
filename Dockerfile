# Contextual Orchestrator — stdlib-only Python, so the image is just the source
# tree on a slim Python base. Runs the OpenAI-compatible server.
#
# Build:  docker build -t contextual-orchestrator .
# Run  :  docker run --rm -p 8000:8000 \
#           -e CONTEXTUAL_ORCHESTRATOR_TOKEN=change-me \
#           -e OPENAI_API_KEY=sk-... \
#           contextual-orchestrator
# Agents: defaults to the bundled mock pool; mount your own and set AGENTS_FILE:
#           -v ./agents.json:/app/agents.json -e AGENTS_FILE=/app/agents.json
# python:3.12-slim
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

WORKDIR /app
COPY contextual_orchestrator/ contextual_orchestrator/
COPY examples/ examples/

ENV AGENTS_FILE=/app/examples/agents.mock.json \
    PORT=8000

RUN useradd --uid 10001 --no-create-home orchestrator
USER orchestrator

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD ["python", "-c", "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz', timeout=2)"]

# --allow-public-bind: 컨테이너 내부 0.0.0.0 바인딩 필요(외부 노출은 호스트 포트 매핑이 결정)
CMD ["sh", "-c", "python -m contextual_orchestrator --serve --agents \"$AGENTS_FILE\" --host 0.0.0.0 --port \"$PORT\" --allow-public-bind"]
