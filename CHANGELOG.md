# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

## [Unreleased]

### Added

- Hourly PR maintenance dispatcher that requests one bounded, exact-target review-repair opportunity from the protected central `.github` control plane.

### Security

- Kept the scheduled caller read-only and model-secret-free while preserving exact-head checks, independent approval, and the existing reviewer credential scheme.
