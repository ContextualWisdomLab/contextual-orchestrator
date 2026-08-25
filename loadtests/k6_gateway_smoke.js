/**
 * k6 smoke/load scenario for the Contextual Orchestrator OpenAI-compatible surface.
 *
 * What this measures
 * ------------------
 * 1. Liveness (`/healthz`) must stay fast and error-free under concurrency — it is the
 *    unauthenticated readiness signal every orchestrator health probe depends on.
 * 2. Authenticated chat throughput against a MOCK agent pool: answers come from the
 *    in-process mock client, so results measure the GATEWAY layer (parsing, routing,
 *    policy, tracing, persistence) — never provider latency.
 *
 * How to run
 * ----------
 *   python -m contextual_orchestrator --serve --agents examples/agents.mock.json \
 *       --auth-token "$GATEWAY_TOKEN" --host 127.0.0.1 --port 8000 &
 *   GATEWAY_TOKEN=... k6 run loadtests/k6_gateway_smoke.js
 *
 * Thresholds are gate-style: the run FAILS when p95 or error rate regress beyond the
 * recorded baseline, so CI can treat this as a performance contract rather than a report.
 */
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.GATEWAY_BASE_URL || "http://127.0.0.1:8000";
const TOKEN = __ENV.GATEWAY_TOKEN || "";
const CHAT_BODY = JSON.stringify({
  model: "mock-generalist",
  messages: [{ role: "user", content: "k6 gateway smoke" }],
});

export const options = {
  scenarios: {
    liveness_probe: {
      executor: "constant-arrival-rate",
      rate: 200,
      timeUnit: "1s",
      duration: "60s",
      preAllocatedVUs: 50,
      maxVUs: 200,
      exec: "probeLiveness",
    },
    chat_throughput: {
      executor: "ramping-arrival-rate",
      startRate: 5,
      timeUnit: "1s",
      stages: [
        { target: 20, duration: "30s" },
        { target: 50, duration: "60s" },
        { target: 20, duration: "30s" },
      ],
      preAllocatedVUs: 50,
      maxVUs: 300,
      exec: "chatCompletion",
    },
  },
  thresholds: {
    // Baseline gates — tune only with a recorded rationale in CHANGELOG/docs.
    // Measured baseline on M-series macOS, combined load (2026-08-25): healthz
    // p95=34.5ms while chat ramps concurrently — the residue is interpreter
    // thread scheduling, not per-request work (median is ~4ms). Tighten after
    // a dedicated scheduling-optimization pass, not speculatively.
    "http_req_duration{name:healthz}": ["p(95)<50"],
    "http_req_duration{name:chat}": ["p(95)<250"],
    "http_req_failed{scenario:liveness_probe}": ["rate<0.001"],
    "http_req_failed{scenario:chat_throughput}": ["rate<0.01"],
  },
};

function authHeaders() {
  return {
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${TOKEN}`,
      connection: "close",
    },
  };
}

export function probeLiveness() {
  const res = http.get(`${BASE_URL}/healthz`, {
    tags: { name: "healthz" },
  });
  check(res, {
    "healthz 200": (r) => r.status === 200,
  });
}

export function chatCompletion() {
  const res = http.post(
    `${BASE_URL}/v1/chat/completions`,
    CHAT_BODY,
    Object.assign(authHeaders(), { tags: { name: "chat" } }),
  );
  check(res, {
    "chat 200": (r) => r.status === 200,
    "chat returns choices": (r) => r.status !== 200 || r.json("choices") !== undefined,
  });
}
