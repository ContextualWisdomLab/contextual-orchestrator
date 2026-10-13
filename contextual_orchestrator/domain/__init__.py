"""Pure domain rules for spend control (standard library only).

Modules in this package hold decisions that must be unit-testable without
network, database, clock, or provider I/O: money and usage value objects, the
per-run / virtual-key / tenant budget composition rule, the provider
limit-exhaustion classification, and tenant identity. Application code
(``contextual_orchestrator.spend_guard``) and storage adapters
(``contextual_orchestrator.spend_metering``) depend on this package; this
package never imports them. See ADR 0138.
"""
