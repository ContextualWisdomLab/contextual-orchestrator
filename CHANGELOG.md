# Changelog

All notable changes to Contextual Orchestrator are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Partition the hash-locked Atheris fuzz dependency by Python interpreter so the Python 3.11 fuzz runner and Python 3.13+ coverage-evidence runners each select one published, reviewed release without weakening `--require-hashes`.

### Documentation

- Add an APA 7 doctoring record for Python environment-marker semantics, Atheris artifact availability, published hashes, and the supported-platform uncertainty boundary.
