"""A capability downgrade must remove a previously populated effort field."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest


@pytest.fixture
def api():
    source = Path(__file__).resolve().parents[1] / 'contextual_orchestrator/reasoning_effort_profile.py'
    spec = importlib.util.spec_from_file_location('effort_omission_subject', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('previous_value', ['high', 'low', None, {'effort': 'high'}])
def test_explicit_omit_removes_existing_native_effort(api, previous_value):
    payload = {'model': 'selected_worker', 'reasoning_effort': previous_value,
               'messages': [{'role': 'user', 'content': 'review source'}],
               'tools': [{'type': 'function', 'function': {'name': 'read_source'}}],
               'stream': True}
    retained_fields = deepcopy({key: value for key, value in payload.items() if key != 'reasoning_effort'})
    profile = api.parse_reasoning_effort_profile({
        'reasoning_effort': 'high', 'unsupported_provider_fallback': 'omit',
        'max_output_tokens': 321, 'temperature': 0.3, 'top_p': 0.8, 'seed': 11,
    })
    result = api.apply_request_profile(payload, profile, supports_reasoning_effort=False,
                                       default_max_output_tokens=999)
    assert 'reasoning_effort' not in result
    assert result is payload
    assert all(result[key] == value for key, value in retained_fields.items())
    assert (result['max_tokens'], result['temperature'], result['top_p'], result['seed']) == (321, 0.3, 0.8, 11)


def test_supported_then_unsupported_payload_obeys_omission(api):
    profile = api.parse_reasoning_effort_profile({'reasoning_effort': 'high',
                                                 'unsupported_provider_fallback': 'omit'})
    payload = {'model': 'selected_worker', 'stream': False}
    api.apply_request_profile(payload, profile, supports_reasoning_effort=True,
                              default_max_output_tokens=99)
    assert payload['reasoning_effort'] == 'high'
    api.apply_request_profile(payload, profile, supports_reasoning_effort=False,
                              default_max_output_tokens=99)
    assert 'reasoning_effort' not in payload


@pytest.mark.parametrize('fallback', ['abstain', 'error'])
def test_non_omission_fallback_remains_fail_closed_without_mutation(api, fallback):
    payload = {'model': 'selected_worker', 'reasoning_effort': 'high', 'temperature': 0.7}
    original = deepcopy(payload)
    profile = api.parse_reasoning_effort_profile({'unsupported_provider_fallback': fallback})
    with pytest.raises(api.EffortProfileError, match='support is unproven'):
        api.apply_request_profile(payload, profile, supports_reasoning_effort=False,
                                  default_max_output_tokens=99)
    assert payload == original


@pytest.mark.parametrize('effort', ['none', 'low', 'medium', 'high'])
def test_supported_native_effort_is_still_forwarded(api, effort):
    profile = api.parse_reasoning_effort_profile({'reasoning_effort': effort})
    result = api.apply_request_profile({'reasoning_effort': 'previous'}, profile,
                                      supports_reasoning_effort=True, default_max_output_tokens=99)
    assert result['reasoning_effort'] == effort


def test_empty_payload_omit_is_idempotent(api):
    profile = api.parse_reasoning_effort_profile({'unsupported_provider_fallback': 'omit'})
    payload = {}
    first = api.apply_request_profile(payload, profile, supports_reasoning_effort=False,
                                     default_max_output_tokens=99).copy()
    assert api.apply_request_profile(payload, profile, supports_reasoning_effort=False,
                                     default_max_output_tokens=99) == first
    assert 'reasoning_effort' not in payload


def test_unconfigured_profile_keeps_compatibility_behavior(api):
    payload = {'reasoning_effort': 'caller_owned'}
    assert api.apply_request_profile(payload, None, supports_reasoning_effort=False,
                                     default_max_output_tokens=99) == {
        'reasoning_effort': 'caller_owned', 'max_tokens': 99,
    }


def test_invalid_profile_is_rejected_before_payload_changes(api):
    payload = {'reasoning_effort': 'previous'}
    with pytest.raises(api.EffortProfileError):
        api.apply_request_profile(payload, object(), supports_reasoning_effort=False,
                                  default_max_output_tokens=99)
    assert payload == {'reasoning_effort': 'previous'}
