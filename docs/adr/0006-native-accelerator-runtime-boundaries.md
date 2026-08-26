# ADR 0006: Native accelerator runtime boundaries

**Status:** Accepted

## Context

The gateway has a CPU PyO3 extension for exact token packing, checked token
arithmetic, and embedding reduction. That narrow in-process boundary does not
prove that vendor GPU runtimes belong in the gateway process or canonical
Compose deployment. Apple MLX targets Apple silicon and unified memory;
NVIDIA GPU containers depend on a configured host driver and Container
Toolkit; Kubernetes exposes GPUs through vendor device plugins and extended
resources. OpenCL defines a portable host/device API, not evidence that a
particular workload is correct, faster, or supportable on an available device.

The existing authenticated MLX integration is an OpenAI-compatible native-host
provider. This repository has no measured CUDA or OpenCL worker runtime,
device-plugin deployment evidence, or externally durable ownership model for
all SQLite/process-local state. Speculative overlays or manifests would claim
an unsupported operating contract.

## Decision

1. Exact CPU token-size arithmetic and vector reduction remain in-process in
   the hash-locked PyO3 wheel. Production limit enforcement fails closed when
   it is unavailable; Python estimates are not an exact-arithmetic fallback.
2. On macOS, MLX remains an authenticated native-host external provider. The
   gateway uses the existing provider transport; MLX/Metal libraries are not
   installed in the Linux gateway image.
3. CUDA or OpenCL execution, if justified by measured vendor-runtime evidence,
   runs as a separate authenticated worker with independent scaling, health,
   resource limits, and rollout. No overlay, Kubernetes manifest, device
   request, or dependency is adopted now.
4. Kubernetes adoption requires a vendor device plugin, explicit GPU resource
   requests/limits, node/runtime evidence, and externalization of credentials,
   agent/catalog state, job state, cost/analytics state, and other local state
   before gateway replicas scale. A same-Pod sidecar is co-scheduled and is not
   an independently scalable GPU worker.
5. Root `compose.yaml` retains service-generated names and forbids
   `container_name`. Its project name defaults to `contextual-orchestrator` and
   may be isolated with `CONTEXTUAL_ORCHESTRATOR_COMPOSE_PROJECT_NAME`.

## Considered alternatives

- Install every accelerator runtime in the gateway image. Rejected because it
  couples incompatible stacks, enlarges the supply chain, and lacks evidence.
- Publish speculative CUDA/OpenCL Compose and Kubernetes examples. Rejected
  because unexecuted manifests are not an adoption contract.
- Run one GPU sidecar per gateway Pod. Rejected as the default because Pod
  containers share scheduling and lifecycle and cannot scale independently.

## Consequences

- The current image remains portable and native CPU arithmetic stays small and
  build-tested.
- macOS MLX operators run and authenticate the native provider separately.
- A future worker needs measured latency, throughput, memory, failure, and cost
  evidence on its named runtime before deployment artifacts land.
- Kubernetes horizontal scaling remains blocked until mutable state and
  credentials have durable external authorities.

## Verification and revisit triggers

Compose tests assert the default/override project name and continued absence of
`container_name`. Revisit only with reproducible native-runtime measurements,
a pinned worker supply chain, authenticated transport, failure/cancellation
tests, and target-host or cluster evidence. Figma is outside scope because this
decision changes no user interface.

## References

Apple Inc. (n.d.). *MLX: An array framework for Apple silicon*. MLX
Documentation. https://ml-explore.github.io/mlx/build/html/index.html

Docker, Inc. (n.d.-a). *Compose file reference: Version and name top-level
elements*. Docker Docs. https://docs.docker.com/reference/compose-file/version-and-name/

Docker, Inc. (n.d.-b). *Services: container_name*. Docker Docs.
https://docs.docker.com/reference/compose-file/services/#container_name

Khronos Group. (2023). *The OpenCL specification, version 3.0*.
https://registry.khronos.org/OpenCL/specs/3.0-unified/html/OpenCL_API.html

Kubernetes Authors. (2025a). *Schedule GPUs*. Kubernetes Documentation.
https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/

Kubernetes Authors. (2025b). *Sidecar containers*. Kubernetes Documentation.
https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/

NVIDIA Corporation. (n.d.). *Installing the NVIDIA Container Toolkit*.
NVIDIA Documentation.
https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
