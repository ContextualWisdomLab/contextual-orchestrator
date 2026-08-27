import http from "k6/http";
import { check } from "k6";
import { Counter, Trend } from "k6/metrics";

const baseUrl = __ENV.BASE_URL || "http://host.docker.internal:18089";
const token = __ENV.AUTH_TOKEN || "synthetic-load-token";
const inferenceVus = Number(__ENV.INFERENCE_VUS || 64);
const iterationsPerVu = Number(__ENV.ITERATIONS_PER_VU || 2);
const providerDelayMs = Number(__ENV.PROVIDER_DELAY_MS || 1000);

const accepted = new Counter("inference_accepted");
const rejected = new Counter("inference_rejected");
const healthLatency = new Trend("health_latency", true);

export const options = {
  scenarios: {
    delayed_inference: {
      executor: "per-vu-iterations",
      exec: "inference",
      vus: inferenceVus,
      iterations: iterationsPerVu,
      maxDuration: "30s",
    },
    liveness_during_inference: {
      executor: "constant-arrival-rate",
      exec: "health",
      rate: 20,
      timeUnit: "1s",
      duration: "5s",
      preAllocatedVUs: 50,
      startTime: "100ms",
    },
  },
  thresholds: {
    checks: ["rate==1"],
    // Isolation invariant, not a production latency guess: liveness must return
    // before the deliberately delayed provider call can finish.
    health_latency: [`p(99)<${providerDelayMs}`],
    http_req_failed: ["rate==0"],
  },
};

export function inference() {
  const response = http.post(
    `${baseUrl}/v1/chat/completions`,
    JSON.stringify({
      model: "synthetic-slow-model",
      mode: "route",
      messages: [{ role: "user", content: "synthetic load request" }],
    }),
    {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      timeout: "10s",
    },
  );
  if (response.status === 200) accepted.add(1);
  if (response.status === 503) rejected.add(1);
  check(response, { "inference completed": (value) => value.status === 200 });
}

export function health() {
  const response = http.get(`${baseUrl}/healthz`, { timeout: "2s" });
  healthLatency.add(response.timings.duration);
  check(response, { "liveness stayed responsive": (value) => value.status === 200 });
}
