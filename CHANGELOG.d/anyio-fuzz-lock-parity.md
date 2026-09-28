# AnyIO security and fuzz-lock parity

Require AnyIO 4.14.2 across the runtime lock and keep both hash-locked fuzz
inputs on the same shared dependency versions. The property-fuzz input no
longer owns a second `typing-extensions` pin; `requirements.lock` is the
constraint authority for both generated fuzz lockfiles.
