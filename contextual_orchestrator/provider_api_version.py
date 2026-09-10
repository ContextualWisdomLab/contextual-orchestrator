"""Per-provider required API-version metadata, applied to every outgoing request.

Some providers require every request to carry an explicit API version --
either as a request header (Anthropic's ``anthropic-version``) or as a URL
query parameter (Azure OpenAI's ``api-version``). This module is the single
data-driven registry for that requirement: adding a new versioned provider
means adding one entry to :data:`PROVIDER_API_VERSIONS`, never a new branch
in the request-dispatch code that actually sends requests
(``ModelClient._provider_url``/``_send_raw`` and its sibling transport
methods in ``orchestrator.py``, all of which key their lookup on
``ModelAgent.provider_name``). This mirrors the org's existing "provider
group names are not hardcoded into routing logic" convention -- the same
shape ``ModelAgent.auth_scheme`` already uses to vary the Authorization
header's value per provider without a per-provider branch in
``format_authorization_header``.

The registry ships empty: no provider configured in this repo today
requires a declared version, so an unregistered ``provider_name`` is a
silent, correct no-op (the omitted argument's own default). See
``docs/planning/adrs/0128-openai-chat-responses-shape-translation.md`` for
why Azure OpenAI and native Anthropic are not populated here yet even
though they motivated this mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class ProviderApiVersion:
    """One provider's required API-version declaration.

    Exactly one of ``header_name``/``query_param_name`` is the expected
    shape for a real provider; nothing here forbids declaring both. ``value``
    is the exact version string sent verbatim, unmodified by this module.
    """

    header_name: str = ""
    query_param_name: str = ""
    value: str = ""

    def __post_init__(self) -> None:
        if not self.header_name and not self.query_param_name:
            raise ValueError(
                "ProviderApiVersion needs a header_name or query_param_name"
            )
        if not self.value.strip():
            raise ValueError("ProviderApiVersion.value must be non-empty")


# provider_name -> its required API version declaration. Empty by default;
# see the module docstring for why. A provider not present here is
# unaffected -- never a hard error, just no header/query injected.
PROVIDER_API_VERSIONS: dict[str, ProviderApiVersion] = {}


def api_version_for(provider_name: str) -> ProviderApiVersion | None:
    """Return the declared API version for a provider name, or ``None``."""
    return PROVIDER_API_VERSIONS.get(provider_name) if provider_name else None


def apply_query_param(url: str, version: ProviderApiVersion | None) -> str:
    """Append a provider's declared version query parameter to a request URL.

    Returns ``url`` unchanged when ``version`` is ``None`` or declares no
    query parameter. An existing query parameter of the same name on
    ``url`` is replaced, never duplicated.
    """
    if version is None or not version.query_param_name:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[version.query_param_name] = version.value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def apply_header(headers: dict[str, str], version: ProviderApiVersion | None) -> None:
    """Inject a provider's declared version header into an outgoing headers dict.

    A no-op when ``version`` is ``None`` or declares no header name.
    """
    if version is not None and version.header_name:
        headers[version.header_name] = version.value
