FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

WORKDIR /src
ENV PYTHONPATH=/src

COPY . .

RUN test -f pyproject.toml || (echo "::error title=ClusterFuzzLite context::Build from the repository root: docker build -f .clusterfuzzlite/Dockerfile ." && exit 64)
RUN python -m compileall contextual_orchestrator tests

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -m compileall -q contextual_orchestrator tests || exit 1
CMD ["python", "-m", "compileall", "-q", "contextual_orchestrator", "tests"]
