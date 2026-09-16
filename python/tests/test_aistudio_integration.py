from __future__ import annotations

import pytest

from unsafie.aistudio.browser import RateLimitError, extract_gemini_text
from unsafie.aistudio.formatter import LLMResponse, clean_model_response, format_chat_prompt


def test_format_chat_prompt_roles() -> None:
    messages = [
        {"role": "system", "content": "You are a test assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
    ]
    prompt = format_chat_prompt(messages)
    assert "**SYSTEM**:\nYou are a test assistant." in prompt
    assert "**USER**:\nHello!" in prompt
    assert "**MODEL**:\nHi there!" in prompt
    assert "**USER**:\nHow are you?" in prompt
    assert prompt.endswith("**MODEL**:\n")


def test_clean_model_response() -> None:
    resp1 = clean_model_response("**MODEL**: 42")
    assert resp1 == "42"
    assert resp1.content == "42"
    assert resp1.text == "42"

    resp2 = clean_model_response("Direct answer")
    assert resp2 == "Direct answer"
    assert isinstance(resp2, LLMResponse)


def test_extract_gemini_text_standard() -> None:
    data = {"candidates": [{"content": {"parts": [{"text": "Hello world"}]}}]}
    assert extract_gemini_text(data) == "Hello world"


def test_extract_gemini_text_429() -> None:
    error_data = {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted",
            "status": "RESOURCE_EXHAUSTED",
        }
    }
    with pytest.raises(RateLimitError):
        extract_gemini_text(error_data)


def test_extract_gemini_text_alkali_proto() -> None:
    alkali_data = [
        [
            [
                [
                    [
                        [
                            [
                                None,
                                "Thinking thoughts...",
                                None,
                                None,
                                None,
                                None,
                                None,
                                None,
                                None,
                                None,
                                None,
                                None,
                                1,
                            ]
                        ],
                        "model",
                    ]
                ]
            ],
            [[[[[[None, "Real answer text"]], "model"]]]],
        ]
    ]
    assert extract_gemini_text(alkali_data) == "Real answer text"
