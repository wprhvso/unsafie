from __future__ import annotations

import secrets
import time
from typing import Any, cast


def convert_json_schema_to_alkali_format(schema: dict[str, Any]) -> list[Any]:
    type_mapping = {
        "string": 1,
        "number": 2,
        "integer": 3,
        "boolean": 4,
        "array": 5,
        "object": 6,
    }
    schema_type = schema.get("type", "string")

    if schema_type == "object":
        properties_dict = cast("dict[str, Any]", schema.get("properties", {}))
        properties = [
            [key, convert_json_schema_to_alkali_format(value)]
            for key, value in properties_dict.items()
        ]
        required_fields = cast(
            "list[str]",
            schema.get("required", [p[0] for p in properties]),
        )
        return [6, None, None, None, None, None, properties, required_fields]

    if schema_type == "array":
        items_dict = cast("dict[str, Any]", schema.get("items", {}))
        return [
            5,
            None,
            None,
            None,
            None,
            convert_json_schema_to_alkali_format(items_dict),
        ]

    return [type_mapping.get(cast("str", schema_type), 1)]


def build_alkali_model_config(
    model: str = "models/gemini-2.5-flash",
    temperature: float = 1.0,
    top_p: float = 0.95,
    output_length: int = 8192,
    thinking_level: int = 0,
    structured_outputs: dict[str, Any] | None = None,
) -> list[Any]:
    model_name_mapping = {
        "gemini-pro-latest": "models/gemini-3.8-flash",
        "gemini-flash-latest": "models/gemini-3.8-flash",
        "gemini-flash-lite-latest": "models/gemini-3.8-flash",
        "gemini-2.5-flash": "models/gemini-3.8-flash",
        "gemini-2.5-pro": "models/gemini-3.8-flash",
        "gemini-2.0-flash": "models/gemini-3.8-flash",
        "3.8": "models/gemini-3.8-flash",
    }
    resolved_model = model_name_mapping.get(model, model)
    if not resolved_model.startswith("models/"):
        resolved_model = f"models/{resolved_model}"

    config_list: list[Any] = [None for _ in range(35)]
    config_list[0] = float(temperature)
    config_list[1] = None
    config_list[2] = resolved_model
    config_list[4] = float(top_p)
    config_list[5] = 64
    config_list[6] = int(output_length)

    # Safety thresholds (BLOCK_NONE / minimal blocking: 5)
    config_list[7] = [
        [None, None, 7, 5],
        [None, None, 8, 5],
        [None, None, 9, 5],
        [None, None, 10, 5],
    ]

    if structured_outputs:
        config_list[8] = "application/json"
        config_list[10] = convert_json_schema_to_alkali_format(structured_outputs)

    config_list[9] = 0
    config_list[13] = 0
    config_list[15] = 0
    config_list[24], config_list[27], config_list[28], config_list[31] = (
        -1,
        "1K",
        thinking_level,
        0,
    )
    config_list[25] = "MEDIA_RESOLUTION_UNSPECIFIED"

    for index in [14, 17, 18, 30, 32, 33, 34]:
        config_list[index] = 0

    return config_list


def build_alkali_drive_resource(
    prompt_id: str,
    messages: list[dict[str, str]],
    system_instruction: str = "",
    model: str = "models/gemini-2.5-flash",
    temperature: float = 1.0,
    top_p: float = 0.95,
    output_length: int = 8192,
) -> list[Any]:
    current_time = time.time()
    seconds = str(int(current_time))
    nanoseconds = int((current_time % 1) * 1_000_000_000)

    def create_message_item(msg: dict[str, str], is_placeholder: bool = False) -> list[Any]:
        item: list[Any] = [None for _ in range(32 if is_placeholder else 33)]
        role = "model" if msg["role"] in ("assistant", "model", "ai", "bot") else "user"
        item[0] = msg["text"]
        item[8] = role
        if role == "model":
            item[16], item[18], item[29] = 1, 472, [[None, item[0]]]
        else:
            item[18] = 11
        item[28], item[30], item[31] = "", 0, 0
        if not is_placeholder:
            item[32] = [seconds, nanoseconds]
        return item

    history = messages[:-1] if len(messages) > 1 else []
    last_msg = messages[-1] if messages else {"role": "user", "text": ""}

    alkali_payload: list[Any] = [None for _ in range(22)]
    alkali_payload[0] = f"prompts/{prompt_id}"
    alkali_payload[3] = build_alkali_model_config(
        model=model,
        temperature=temperature,
        top_p=top_p,
        output_length=output_length,
    )
    alkali_payload[4] = [
        "Injected",
        None,
        ["V", 1, ""],
        None,
        [[seconds, nanoseconds], ["V", 1, ""]],
        [1, 1, 1],
        None,
        None,
        None,
        None,
        [],
        [["version", "1"], ["promptType", "CHUNKED_PROMPT"]],
    ]
    alkali_payload[12] = [system_instruction] if system_instruction else []
    alkali_payload[13] = [
        [create_message_item(m) for m in history],
        [create_message_item(last_msg, is_placeholder=True)],
    ]
    alkali_payload[21] = [[["version", "1"], ["promptType", "CHUNKED_PROMPT"]]]

    return [alkali_payload]


def generate_prompt_id() -> str:
    return secrets.token_urlsafe(16).replace("-", "").replace("_", "")
