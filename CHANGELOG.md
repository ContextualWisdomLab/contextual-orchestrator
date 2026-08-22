# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- Separate local product evidence from fail-closed protected-head release
  authorization, with machine-readable blocker reasons and no sensitive payloads.
- Return the same `agent_not_found` error code for GET, PATCH, and DELETE worker
  agent requests that address an unknown or unauthorized pool member.
