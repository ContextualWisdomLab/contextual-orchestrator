#!/usr/bin/env python3
"""Apply the reviewed import-safe provider transport integration exactly once."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment or fail closed before writing."""
    occurrences = text.count(old)
    if occurrences != 1:
        raise RuntimeError(f"{label}: expected one source fragment, found {occurrences}")
    return text.replace(old, new, 1)


def rewrite(path: str, transform) -> None:
    """Rewrite one UTF-8 repository file with a deterministic transform."""
    target = ROOT / path
    original = target.read_text(encoding="utf-8")
    updated = transform(original)
    if updated == original:
        raise RuntimeError(f"{path}: transform produced no change")
    target.write_text(updated, encoding="utf-8")


def update_package_init(text: str) -> str:
    """Remove import-time monkey-patching from the public package initializer."""
    old = '''from .orchestrator import ModelAgent, ModelClient as _ModelClient, TaskOrchestrator, WorkflowStep, load_agents
from .provider_transport import install_provider_transport as _install_provider_transport
from .token_counting import HeuristicTokenCounter, build_token_counter

_install_provider_transport(_ModelClient)
'''
    new = '''from .orchestrator import ModelAgent, TaskOrchestrator, WorkflowStep, load_agents
from .token_counting import HeuristicTokenCounter, build_token_counter
'''
    return replace_once(text, old, new, "package initializer")


def update_provider_transport(text: str) -> str:
    """Keep transport primitives while deleting the class-mutation installer."""
    old_docstring = '''"""DNS-pinned HTTPS transport for validated model-provider egress.

The legacy orchestration module validates provider DNS answers before sending a
request. A normal URL opener resolves the hostname again during connection,
which leaves a time-of-check/time-of-use gap if DNS changes between validation
and socket creation. This module installs a narrow transport extension on
``ModelClient``: the second validation answer is retained, the socket connects
only to one of those approved addresses, TLS still verifies the original
hostname, environment proxies are bypassed, and redirects are rejected.
"""'''
    new_docstring = '''"""DNS-pinned HTTPS primitives for validated model-provider egress.

``ModelClient`` owns policy validation and request dispatch directly. This
module contains only focused connection, response-cleanup, and public-address
validation helpers, so importing the package never mutates another class.
"""'''
    text = replace_once(text, old_docstring, new_docstring, "provider transport docstring")
    text = replace_once(
        text,
        '''import urllib.error
import urllib.request
from urllib.parse import urlparse
''',
        "",
        "provider transport obsolete urllib imports",
    )
    marker = "\n\ndef install_provider_transport(model_client_type: type[Any]) -> None:\n"
    if text.count(marker) != 1:
        raise RuntimeError("provider transport installer marker changed")
    return text[: text.index(marker)] + "\n"


def update_orchestrator(text: str) -> str:
    """Make the canonical model client own DNS validation and pinned dispatch."""
    text = replace_once(
        text,
        '''import hashlib
import ipaddress
import json
''',
        '''import hashlib
import http.client
import json
''',
        "orchestrator imports",
    )
    text = replace_once(
        text,
        '''from .credentials import NotConfigured, get_credential
''',
        '''from .credentials import NotConfigured, get_credential
from .provider_transport import (
    _PinnedHTTPSConnection,
    _ProviderHTTPResponse,
    _validated_public_addresses,
)
''',
        "orchestrator transport imports",
    )
    text = replace_once(
        text,
        '''        self._ssl_context = self._build_ssl_context(ca_bundle, verify_tls)
''',
        '''        self._ssl_context = self._build_ssl_context(ca_bundle, verify_tls)
        # Explicit test seam; production uses the DNS-pinned TLS connection.
        self._https_connection_class = _PinnedHTTPSConnection
''',
        "model client connection class",
    )
    old_open = '''    def _open_provider(self, request: urllib.request.Request) -> Any:
        """Open a provider request built from a validated provider URL."""
        return urllib.request.urlopen(  # nosec B310 - URL from _provider_url after egress/SSRF validation. nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            request,
            timeout=self.timeout,
            context=self._ssl_context,
        )
'''
    new_open = '''    def _open_provider(self, request: urllib.request.Request) -> Any:
        """Open one request using only the validation-time provider addresses.

        Public provider methods require HTTPS and call ``_validate_provider``
        first. Plain HTTP remains a narrow private-loopback integration seam;
        production provider validation rejects it before credentials are used.
        """
        parsed = urlparse(request.full_url)
        if parsed.scheme == "http":
            return urllib.request.urlopen(  # nosec B310 - public validation rejects HTTP; private loopback test seam only. nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                request,
                timeout=self.timeout,
            )
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("provider request URL must use http(s)")

        port = parsed.port or 443
        pin_key = (parsed.hostname.lower(), port)
        addresses = getattr(self._local, "provider_address_pins", {}).get(pin_key)
        if not addresses:
            raise RuntimeError("provider request has no validated address pin")

        target = parsed.path or "/"
        if parsed.params:
            target = f"{target};{parsed.params}"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        headers = dict(request.header_items())
        headers["Connection"] = "close"

        last_error: BaseException | None = None
        for pinned_ip in addresses:
            connection = self._https_connection_class(
                parsed.hostname,
                pinned_ip,
                port,
                self.timeout,
                self._ssl_context,
            )
            try:
                connection.request(
                    request.get_method(),
                    target,
                    body=request.data,
                    headers=headers,
                )
                response = connection.getresponse()
            except (OSError, http.client.HTTPException) as exc:
                connection.close()
                last_error = exc
                continue
            if response.status >= 300:
                status = response.status
                reason = response.reason
                response_headers = response.headers
                response.close()
                connection.close()
                raise urllib.error.HTTPError(
                    request.full_url,
                    status,
                    reason,
                    response_headers,
                    None,
                )
            return _ProviderHTTPResponse(response, connection)
        raise urllib.error.URLError(last_error or "provider connection failed")
'''
    text = replace_once(text, old_open, new_open, "model client pinned opener")

    old_validate = '''    def _validate_provider(self, agent: ModelAgent) -> None:
        """Reject unsafe remote model endpoints before any egress happens."""
        # Runtime secret must be resolvable from the KV — never an env var name,
        # never a silent os.getenv fallback. (Legacy api_key_env, if set, is used
        # only as the credential NAME; see ModelAgent.credential_name.)
        if get_credential(agent.credential_name) is None:
            raise NotConfigured(
                f"{agent.id} requires a resolvable credential '{agent.credential_name}' in the KV "
                "(this replaces the legacy api_key_env environment pattern)"
            )
        parsed = urlparse(agent.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError(f"{agent.id} base_url must use https")
        allowed_hosts = {
            host.strip().lower()
            for host in os.environ.get("CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", "").split(",")
            if host.strip()
        }
        hostname = parsed.hostname.lower()
        if allowed_hosts and hostname not in allowed_hosts:
            raise RuntimeError(f"{agent.id} provider host is not allowlisted")
        for address in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM):
            ip_address = ipaddress.ip_address(address[4][0])
            # ``not is_global`` rejects every non-globally-routable target, including
            # ranges that carry none of the explicit flags below — notably RFC 6598
            # shared address space (100.64.0.0/10, carrier-grade NAT / cloud-internal)
            # and the unspecified address. The explicit flags are kept because some
            # non-public multicast addresses report ``is_global`` True and must still
            # be blocked.
            if (
                not ip_address.is_global
                or ip_address.is_private
                or ip_address.is_loopback
                or ip_address.is_link_local
                or ip_address.is_multicast
                or ip_address.is_reserved
            ):
                raise RuntimeError(f"{agent.id} provider resolves to non-public address")
'''
    new_validate = '''    def _validate_provider(self, agent: ModelAgent) -> None:
        """Validate one provider and retain its exact approved DNS answer."""
        # Clear every prior thread-local pin before any credential or URL check so
        # a failed revalidation can never reuse an earlier approved destination.
        self._local.provider_address_pins = {}
        # Runtime secret must be resolvable from the KV — never an env var name,
        # never a silent os.getenv fallback. (Legacy api_key_env, if set, is used
        # only as the credential NAME; see ModelAgent.credential_name.)
        if get_credential(agent.credential_name) is None:
            raise NotConfigured(
                f"{agent.id} requires a resolvable credential '{agent.credential_name}' in the KV "
                "(this replaces the legacy api_key_env environment pattern)"
            )
        parsed = urlparse(agent.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError(f"{agent.id} base_url must use https")
        allowed_hosts = {
            host.strip().lower()
            for host in os.environ.get("CONTEXTUAL_ORCHESTRATOR_ALLOWED_PROVIDER_HOSTS", "").split(",")
            if host.strip()
        }
        hostname = parsed.hostname.lower()
        if allowed_hosts and hostname not in allowed_hosts:
            raise RuntimeError(f"{agent.id} provider host is not allowlisted")
        port = parsed.port or 443
        addresses = _validated_public_addresses(hostname, port, agent.id)
        self._local.provider_address_pins[(hostname, port)] = addresses
'''
    return replace_once(text, old_validate, new_validate, "model client provider validation")


def update_transport_tests(text: str) -> str:
    """Replace installer assertions with the import-side-effect regression."""
    text = replace_once(
        text,
        '''    _validated_public_addresses,
    install_provider_transport,
)
''',
        '''    _validated_public_addresses,
)
''',
        "transport test imports",
    )
    old_test = '''def test_transport_installer_is_idempotent() -> None:
    """Repeated package initialization cannot wrap validation more than once."""
    validate_method = ModelClient._validate_provider
    open_method = ModelClient._open_provider
    install_provider_transport(ModelClient)
    assert ModelClient._validate_provider is validate_method
    assert ModelClient._open_provider is open_method
'''
    new_test = '''def test_package_import_keeps_model_client_transport_canonical() -> None:
    """Importing the package cannot mutate canonical provider methods."""
    assert ModelClient._validate_provider.__module__ == "contextual_orchestrator.orchestrator"
    assert ModelClient._open_provider.__module__ == "contextual_orchestrator.orchestrator"
    assert not hasattr(ModelClient, "_dns_pinned_transport_installed")
    assert ModelClient()._https_connection_class is _PinnedHTTPSConnection
'''
    text = replace_once(text, old_test, new_test, "transport import-side-effect test")
    return replace_once(
        text,
        "    assert resolver.call_count == 2\n",
        "    assert resolver.call_count == 1\n",
        "single DNS resolution assertion",
    )


def update_changelog(text: str) -> str:
    """Record the buyer-visible import-safety correction."""
    needle = "- Pin each HTTPS provider connection to the exact public addresses approved during validation, preserve the original hostname for TLS verification, bypass environment proxy resolution, and reject redirects to close DNS-rebinding and credential-forwarding SSRF paths.\n"
    addition = (
        needle
        + "- Integrate DNS-pinned provider dispatch directly into `ModelClient` so package import performs no optional-adapter monkey-patching or order-dependent class mutation.\n"
    )
    return replace_once(text, needle, addition, "changelog security entry")


def main() -> None:
    """Apply every exact transform and leave verification to the workflow."""
    rewrite("contextual_orchestrator/__init__.py", update_package_init)
    rewrite("contextual_orchestrator/provider_transport.py", update_provider_transport)
    rewrite("contextual_orchestrator/orchestrator.py", update_orchestrator)
    rewrite("tests/test_provider_address_pinning.py", update_transport_tests)
    rewrite("CHANGELOG.md", update_changelog)


if __name__ == "__main__":
    main()
