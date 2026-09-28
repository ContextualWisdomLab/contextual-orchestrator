"""Verify GitHub Actions OIDC identities for production review workloads."""

from __future__ import annotations

import time
from collections.abc import Mapping

import jwt

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = f"{ISSUER}/.well-known/jwks"


class GitHubReviewOIDC:
    """Map a verified central Actions job identity to a review workload."""

    def __init__(
        self,
        *,
        audience: str,
        owner_id: str,
        repository_id: str,
        workflows: Mapping[str, str],
        key_client: jwt.PyJWKClient | None = None,
    ) -> None:
        if (
            not audience
            or not isinstance(owner_id, str)
            or not owner_id.isascii()
            or not owner_id.isdecimal()
            or not isinstance(repository_id, str)
            or not repository_id.isascii()
            or not repository_id.isdecimal()
            or not workflows
        ):
            raise ValueError(
                "OIDC audience, owner ID, central repository ID, and workflows are required"
            )
        if set(workflows) - {"opencode", "noema", "strix"} or len(
            set(workflows.values())
        ) != len(workflows):
            raise ValueError("OIDC workflows must uniquely identify review workloads")
        if any(
            not isinstance(value, str)
            or not value.startswith("ContextualWisdomLab/.github/.github/workflows/")
            or not value.endswith("@refs/heads/main")
            for value in workflows.values()
        ):
            raise ValueError("OIDC workflows must be central main-branch workflows")
        self.audience = audience
        self.owner_id = owner_id
        self.repository_id = repository_id
        self.workflows = dict(workflows)
        self._keys = key_client or jwt.PyJWKClient(
            JWKS_URL, cache_jwk_set=True, lifespan=300, timeout=5, cooldown_duration=300
        )

    def identity(self, token: str) -> str | None:
        """Return workload only for a signed central job token."""
        try:
            if not isinstance(token, str) or len(token) > 16384:
                return None
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 128
            ):
                return None
            key = self._keys.get_signing_key_from_jwt(token)
            if (
                key.algorithm_name != "RS256"
                or key.key_type != "RSA"
                or key.public_key_use != "sig"
            ):
                return None
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=ISSUER,
                leeway=30,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "iat",
                        "nbf",
                        "exp",
                        "repository",
                        "repository_id",
                        "repository_owner",
                        "repository_owner_id",
                        "workflow_ref",
                        "run_id",
                    ],
                    "strict_aud": True,
                    "enforce_minimum_key_length": True,
                },
            )
            now = int(time.time())
            issued, expiry, not_before = (
                claims[name] for name in ("iat", "exp", "nbf")
            )
            if any(
                type(value) is not int for value in (issued, expiry, not_before)
            ) or not (
                issued <= now + 30
                and not_before <= now + 30
                and now < expiry <= issued + 600
            ):
                return None
            if (
                claims["repository_owner_id"] != self.owner_id
                or claims["repository_owner"] != "ContextualWisdomLab"
                or claims["repository"] != "ContextualWisdomLab/.github"
                or claims["repository_id"] != self.repository_id
                or not isinstance(claims["sub"], str)
                or not claims["sub"]
                or not isinstance(claims["run_id"], str)
                or not claims["run_id"].isdecimal()
            ):
                return None
            workload = next(
                (
                    name
                    for name, ref in self.workflows.items()
                    if claims["workflow_ref"] == ref
                ),
                None,
            )
            return workload
        except (
            jwt.PyJWTError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OSError,
        ):
            return None
