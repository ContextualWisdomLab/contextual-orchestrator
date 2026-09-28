"""Signed GitHub Actions identity is scoped to one review workload."""

import base64
import json
import sys
import time

import jwt
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from contextual_orchestrator import review_gateway
from contextual_orchestrator.credentials import (
    InMemoryCredentialBackend,
    delete_credential,
    register_credential,
    set_backend,
)
from contextual_orchestrator.review_oidc import GitHubReviewOIDC
from contextual_orchestrator.server import RequestError


@pytest.fixture(autouse=True)
def _fresh_backend():
    set_backend(InMemoryCredentialBackend())
    try:
        yield
    finally:
        set_backend(None)


def _encoded(value):
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


def _token(private_key, claims, header=None):
    signing_input = f"{_encoded(header or {'alg': 'RS256', 'kid': 'fixture'})}.{_encoded(claims)}".encode()
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def test_signed_review_oidc_claims_and_signature_fail_closed():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "fixture",
                "n": base64.urlsafe_b64encode(numbers.n.to_bytes(256, "big"))
                .rstrip(b"=")
                .decode(),
                "e": base64.urlsafe_b64encode(numbers.e.to_bytes(3, "big"))
                .rstrip(b"=")
                .decode(),
            }
        ]
    }
    signing_key = jwt.PyJWK.from_dict(jwks["keys"][0])

    class StaticKeys:
        def get_signing_key_from_jwt(self, token):
            if jwt.get_unverified_header(token).get("kid") != "fixture":
                raise jwt.PyJWKClientError("unknown key")
            return signing_key

    verifier = GitHubReviewOIDC(
        audience="contextual-orchestrator/review",
        owner_id="295022177",
        repository_id="1274066402",
        workflows={
            "opencode": "ContextualWisdomLab/.github/.github/workflows/opencode-review-dispatch.yml@refs/heads/main"
        },
        key_client=StaticKeys(),
    )
    now = int(time.time())
    claims = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "contextual-orchestrator/review",
        "sub": "repo:ContextualWisdomLab/.github:ref:refs/heads/main",
        "repository": "ContextualWisdomLab/.github",
        "repository_id": "1274066402",
        "repository_owner": "ContextualWisdomLab",
        "repository_owner_id": "295022177",
        "repository_visibility": "public",
        "ref": "refs/heads/main",
        "workflow_ref": "ContextualWisdomLab/.github/.github/workflows/opencode-review-dispatch.yml@refs/heads/main",
        "run_id": "123456",
        "iat": now - 1,
        "nbf": now - 1,
        "exp": now + 240,
    }
    valid = _token(private_key, claims)
    assert verifier.identity(valid) == "opencode:1274066402:123456"
    assert verifier.requires_zdr(valid) is True
    assert (
        verifier.identity(
            _token(
                private_key,
                claims
                | {
                    "sub": "repo:ContextualWisdomLab@295022177/.github@1274066402:ref:refs/heads/main"
                },
            )
        )
        == "opencode:1274066402:123456"
    )
    assert (
        verifier.identity(_token(private_key, claims | {"run_id": "654321"}))
        == "opencode:1274066402:654321"
    )
    assert (
        verifier.identity(
            _token(
                private_key,
                claims
                | {
                    "repository": "ContextualWisdomLab/fast-mlsirm",
                    "repository_id": "12345",
                    "sub": "repo:ContextualWisdomLab/fast-mlsirm:ref:refs/heads/develop",
                    "ref": "refs/heads/develop",
                },
            )
        )
        is None
    )
    noema = GitHubReviewOIDC(
        audience="contextual-orchestrator/review",
        owner_id="295022177",
        repository_id="1274066402",
        workflows={
            "noema": "ContextualWisdomLab/.github/.github/workflows/noema-review.yml@refs/heads/main"
        },
        key_client=StaticKeys(),
    )
    target_claims = claims | {
        "sub": "repo:ContextualWisdomLab/contextual-orchestrator:pull_request",
        "repository": "ContextualWisdomLab/contextual-orchestrator",
        "repository_id": "1277018702",
        "repository_visibility": "private",
        "workflow_ref": "ContextualWisdomLab/.github/.github/workflows/noema-review.yml@refs/heads/main",
    }
    assert (
        noema.identity(_token(private_key, target_claims)) == "noema:1277018702:123456"
    )
    assert noema.requires_zdr(_token(private_key, target_claims)) is True
    assert noema.requires_zdr(_token(private_key, target_claims | {"repository_visibility": "public"})) is False
    assert noema.requires_zdr(_token(private_key, target_claims | {"repository_visibility": "internal"})) is True
    assert noema.requires_zdr(_token(private_key, target_claims | {"repository_visibility": "unknown"})) is True
    assert noema.requires_zdr(_token(private_key, {key: value for key, value in target_claims.items() if key != "repository_visibility"})) is True
    assert (
        noema.identity(
            _token(private_key, target_claims | {"repository_owner_id": "7"})
        )
        is None
    )
    assert (
        noema.identity(
            _token(
                private_key,
                target_claims
                | {
                    "repository": "ContextualWisdomLab/.github",
                    "repository_id": "12345",
                },
            )
        )
        is None
    )
    strix = GitHubReviewOIDC(
        audience="contextual-orchestrator/review",
        owner_id="295022177",
        repository_id="1274066402",
        workflows={
            "strix": "ContextualWisdomLab/.github/.github/workflows/strix.yml@refs/heads/main"
        },
        key_client=StaticKeys(),
    )
    assert (
        strix.identity(
            _token(
                private_key,
                target_claims
                | {
                    "workflow_ref": "ContextualWisdomLab/.github/.github/workflows/strix.yml@refs/heads/main"
                },
            )
        )
        == "strix:1277018702:123456"
    )
    assert (
        verifier.identity(
            _token(private_key, claims, {"alg": "RS256", "kid": "unknown"})
        )
        is None
    )
    for changed in (
        {"iss": "https://attacker.example"},
        {"aud": "other"},
        {"aud": ["contextual-orchestrator/review"]},
        {"repository_id": "not-an-id"},
        {"repository_id": "12345"},
        {"repository": "attacker/.github"},
        {"repository_owner_id": "7"},
        {"repository_owner": "attacker"},
        {
            "workflow_ref": "ContextualWisdomLab/.github/.github/workflows/strix.yml@refs/heads/main"
        },
        {"exp": now - 1},
        {"iat": now + 60},
        {"nbf": now + 60},
        {"exp": now + 3600},
        {"run_id": ""},
        {"run_id": "١٢٣٤٥٦"},
        {"sub": ""},
    ):
        assert verifier.identity(_token(private_key, claims | changed)) is None
    assert (
        verifier.identity(
            _token(private_key, claims, {"alg": "none", "kid": "fixture"})
        )
        is None
    )
    assert verifier.identity(valid[:-3] + "xxx") is None
    assert verifier.identity("not.a.jwt") is None
    assert (
        verifier.identity(
            _token(
                rsa.generate_private_key(public_exponent=65537, key_size=2048), claims
            )
        )
        is None
    )


def test_review_oidc_rejects_ambiguous_workflow_configuration():
    with pytest.raises(ValueError):
        GitHubReviewOIDC(
            audience="a",
            owner_id="1",
            repository_id="1274066402",
            workflows={"opencode": "same", "strix": "same"},
            key_client=object(),
        )


def test_production_oidc_mode_uses_only_admin_kv_and_scoped_job_identity(monkeypatch):
    register_credential(review_gateway.REVIEW_ADMIN_CREDENTIAL_NAME, "admin-secret")
    captured = {}
    workflow = "ContextualWisdomLab/.github/.github/workflows/opencode-review-dispatch.yml@refs/heads/main"
    monkeypatch.setattr(
        review_gateway, "build_review_orchestrator", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        review_gateway, "serve", lambda _orchestrator, **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr(
        review_gateway,
        "GitHubReviewOIDC",
        lambda **kwargs: captured.setdefault(
            "verifier",
            type(
                "Verifier",
                (),
                {
                    "identity": lambda self, token: {
                        "signed-job": "opencode:1274066402:123456",
                        "other-signed-job": "opencode:1274066402:654321",
                    }.get(token),
                    "requires_zdr": lambda self, token: True if token == "signed-job" else None,
                },
            )(),
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_gateway",
            "--production",
            "--preseeded-kv",
            "--github-oidc-audience",
            "contextual-orchestrator/review",
            "--github-oidc-owner-id",
            "295022177",
            "--github-oidc-repository-id",
            "1274066402",
            "--github-oidc-workflow",
            f"opencode={workflow}",
        ],
    )
    review_gateway.main()
    security = captured["security"]
    headers = {"authorization": "Bearer signed-job"}
    assert security.authorize(headers, "inference", "127.0.0.1") == "message_delivery"
    assert security.principal_id(headers) != security.principal_id(
        {"authorization": "Bearer admin-secret"}
    )
    other_headers = {"authorization": "Bearer other-signed-job"}
    assert (
        security.authorize(other_headers, "inference", "127.0.0.1")
        == "message_delivery"
    )
    assert security.principal_id(headers) != security.principal_id(other_headers)
    assert security.zdr_required(headers) is True
    with pytest.raises(RequestError):
        security.zdr_required(other_headers)
    for token, scope in (
        ("signed-job", "admin"),
        ("admin-secret", "inference"),
        ("other", "inference"),
    ):
        with pytest.raises(RequestError):
            security.authorize({"authorization": f"Bearer {token}"}, scope, "127.0.0.1")
    delete_credential(review_gateway.REVIEW_ADMIN_CREDENTIAL_NAME)
    with pytest.raises(RequestError):
        security.authorize(
            {"authorization": "Bearer admin-secret"}, "admin", "127.0.0.1"
        )
    assert security.authorize(headers, "inference", "127.0.0.1") == "message_delivery"


@pytest.mark.parametrize(
    "extra,expected",
    [
        (["--github-oidc-audience", "a"], "require --github-oidc-workflow"),
        (
            ["--github-oidc-repository-id", "1274066402"],
            "require --github-oidc-workflow",
        ),
        (
            ["--github-oidc-workflow", "opencode=bad"],
            "requires production, audience, owner ID, and central repository ID",
        ),
        (
            [
                "--github-oidc-workflow",
                "opencode=bad",
                "--github-oidc-audience",
                "a",
                "--github-oidc-owner-id",
                "295022177",
            ],
            "requires production, audience, owner ID, and central repository ID",
        ),
        (
            [
                "--github-oidc-workflow",
                "opencode=bad",
                "--github-oidc-audience",
                "a",
                "--github-oidc-owner-id",
                "295022177",
                "--github-oidc-repository-id",
                "1274066402",
                "--inference-token-key",
                "TOKEN",
            ],
            "cannot be combined",
        ),
        (
            [
                "--github-oidc-workflow",
                "opencode=bad",
                "--github-oidc-audience",
                "a",
                "--github-oidc-owner-id",
                "295022177",
                "--github-oidc-repository-id",
                "1274066402",
            ],
            "central main-branch workflows",
        ),
    ],
)
def test_oidc_startup_rejects_incomplete_or_mixed_authority(
    monkeypatch, capsys, extra, expected
):
    monkeypatch.setattr(
        sys, "argv", ["review_gateway", "--production", "--preseeded-kv", *extra]
    )
    with pytest.raises(SystemExit):
        review_gateway.main()
    assert expected in capsys.readouterr().err
