Fix free-route quota recovery to honor provider-declared retry timing across
chat, passthrough and structured requests. Requests with unavailable retry
timing return an honest quota failure without a guessed retry deadline.
Eligible alternatives remain available, and a fresh explicit provider success
restores quota admission.
