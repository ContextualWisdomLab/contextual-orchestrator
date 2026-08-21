"""Apply and verify Responses multimodal synthesis fixes for PR 805."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one repository command and surface captured output."""

    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace one reviewed fragment or fail closed if the branch moved."""

    if new in text:
        return text
    if text.count(old) != 1:
        raise SystemExit(f"refusing unknown {label} shape")
    return text.replace(old, new, 1)


def _add_regressions() -> None:
    """Add image-preservation and multi-turn guidance regressions first."""

    path = ROOT / "tests/test_openai_passthrough.py"
    text = path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        '''from contextual_orchestrator.orchestrator import (  # noqa: E402
    BudgetExceededError,
    _FastMLSIJudgeAdapter,
)
''',
        '''from contextual_orchestrator.orchestrator import (  # noqa: E402
    BudgetExceededError,
    _FastMLSIJudgeAdapter,
    _responses_to_chat_payload,
)
''',
        label="passthrough helper import",
    )
    anchor = '''def test_proxy_completion_forwards_response_format_and_returns_full_shape() -> None:
'''
    regressions = r'''def test_responses_translation_preserves_input_image_content() -> None:
    translated = _responses_to_chat_payload(
        {
            "model": "mock-planner",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Inspect this image"},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,AA==",
                            "detail": "high",
                        },
                    ],
                }
            ],
        }
    )

    assert translated["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this image"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,AA==",
                        "detail": "high",
                    },
                },
            ],
        }
    ]


def test_final_synthesis_attaches_private_evidence_to_latest_user_turn() -> None:
    result = _build().proxy_completion(
        {
            "model": "mock-planner",
            "messages": [
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
                {"role": "user", "content": "Current task"},
            ],
            "response_format": {"type": "json_object"},
        }
    )

    messages = result["echo"]["messages"]
    assert messages[0]["content"] == "Earlier question"
    assert messages[2]["content"].startswith("Current task")
    assert "Verified workflow evidence" in messages[2]["content"]


'''
    if regressions not in text:
        if anchor not in text:
            raise SystemExit("refusing unknown passthrough regression insertion point")
        text = text.replace(anchor, regressions + anchor, 1)
    path.write_text(text, encoding="utf-8")


def _apply_repair() -> None:
    """Preserve Responses images and place evidence on the current user turn."""

    path = ROOT / "contextual_orchestrator/orchestrator.py"
    text = path.read_text(encoding="utf-8")
    anchor = '''def _responses_to_chat_payload(request: dict[str, Any]) -> dict[str, Any]:
'''
    helper = '''def _responses_message_content(value: Any) -> str | list[dict[str, Any]]:
    """Translate Responses message content without discarding image evidence."""

    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[dict[str, Any]] = []
    text_only = True
    for item in value:
        if isinstance(item, str):
            parts.append({"type": "text", "text": item})
            continue
        if not isinstance(item, dict):
            raise ValueError("Responses message content parts must be strings or objects")
        part_type = str(item.get("type", "")).lower()
        if part_type in {"input_text", "output_text", "text"}:
            part_text = item.get("text")
            if not isinstance(part_text, str):
                raise ValueError("Responses text content requires text")
            parts.append({"type": "text", "text": part_text})
            continue
        if part_type in {"input_image", "image_url"}:
            raw_image = item.get("image_url")
            if isinstance(raw_image, str):
                image: dict[str, Any] = {"url": raw_image}
            elif isinstance(raw_image, dict) and isinstance(raw_image.get("url"), str):
                image = dict(raw_image)
            else:
                raise ValueError("Responses image content requires image_url")
            detail = item.get("detail")
            if isinstance(detail, str) and "detail" not in image:
                image["detail"] = detail
            parts.append({"type": "image_url", "image_url": image})
            text_only = False
            continue
        fallback_text = item.get("text")
        if isinstance(fallback_text, str):
            parts.append({"type": "text", "text": fallback_text})
            continue
        raise ValueError(
            f"unsupported Responses message content part: {part_type or 'unknown'}"
        )
    if text_only:
        return "".join(str(part["text"]) for part in parts)
    return parts


'''
    if helper not in text:
        if anchor not in text:
            raise SystemExit("refusing unknown Responses conversion insertion point")
        text = text.replace(anchor, helper + anchor, 1)
    text = _replace_once(
        text,
        '''            content = _responses_text(item.get("content"))
            if content:
                messages.append({"role": role, "content": content})
''',
        '''            content = _responses_message_content(item.get("content"))
            if content:
                messages.append({"role": role, "content": content})
''',
        label="Responses message content conversion",
    )
    old_guidance = '''        guidance_index = next(
            (index for index, message in enumerate(synthesis_messages) if message.get("role") == "user"),
            0 if synthesis_messages and synthesis_messages[0].get("role") == "system" else None,
        )
'''
    new_guidance = '''        guidance_index = next(
            (
                index
                for index in range(len(synthesis_messages) - 1, -1, -1)
                if synthesis_messages[index].get("role") == "user"
            ),
            0 if synthesis_messages and synthesis_messages[0].get("role") == "system" else None,
        )
'''
    text = _replace_once(text, old_guidance, new_guidance, label="synthesis guidance target")
    path.write_text(text, encoding="utf-8")

    changelog_path = ROOT / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    marker = "## [Unreleased]\n"
    entry = (
        "\n- Responses-to-Chat orchestration now preserves `input_image` content through "
        "the conducted and final synthesis paths, and private workflow evidence is attached "
        "to the latest user turn in multi-turn conversations.\n"
    )
    if entry.strip() not in changelog:
        if marker not in changelog:
            raise SystemExit("refusing unknown changelog structure")
        changelog = changelog.replace(marker, marker + entry, 1)
    changelog_path.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Prove RED, apply the repair, then prove focused and full GREEN."""

    _add_regressions()
    focused = (
        "tests/test_openai_passthrough.py::test_responses_translation_preserves_input_image_content",
        "tests/test_openai_passthrough.py::test_final_synthesis_attaches_private_evidence_to_latest_user_turn",
    )
    red = _run(sys.executable, "-m", "pytest", "-q", *focused, check=False)
    if red.returncode == 0:
        raise SystemExit("Responses multimodal regressions unexpectedly passed before repair")
    _apply_repair()
    _run(sys.executable, "-m", "pytest", "-q", *focused)
    _run(sys.executable, "-m", "pytest", "-q")


if __name__ == "__main__":
    main()
