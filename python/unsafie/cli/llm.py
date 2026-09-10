import base64
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from unsafie.cli.client import client
from unsafie.mime import sniff_mime
from unsafie_wire import markers


def _process_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    processed = []
    for part in parts:
        ptype = part.get("type", "text")
        if ptype == "image":
            path_str = part.get("path")
            if path_str:
                p = Path(path_str)
                if not p.is_file():
                    sys.stderr.write(f"warning: image file not found: {path_str}\n")
                    continue
                data = p.read_bytes()
                mime = sniff_mime(data, p.name)
                b64 = base64.b64encode(data).decode("ascii")
                processed.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64,
                    },
                })
            elif "data" in part or "source" in part:
                processed.append(part)
        else:
            processed.append(part)
    return processed


def run(
    *,
    payload: dict[str, Any] | None = None,
    raw: bool = False,
) -> dict[str, Any]:
    if payload is None:
        raw_in = sys.stdin.read().strip()
        if not raw_in:
            return {"ok": False, "error": "empty input: JSON payload expected on stdin"}
        try:
            payload = json.loads(raw_in)
        except json.JSONDecodeError:
            # If plain text was provided, wrap it into a prompt
            payload = {"prompt": raw_in}

    call_id = f"call_{uuid.uuid4().hex[:8]}"
    model_name = "gemini-flash-latest"

    # Emit start marker to stderr for Live UI
    sys.stderr.write(markers.llm_start(call_id, model_name) + "\n")
    sys.stderr.flush()

    if payload is not None:
        parts = payload.get("parts")
        if parts and isinstance(parts, list):
            payload["parts"] = _process_parts(parts)

    cli = client()
    try:
        res = cli.call("POST", "/llm/generate", body=payload, timeout=600.0)
    except Exception as e:
        sys.stderr.write(markers.llm_end(call_id, usage={"error": str(e)}) + "\n")
        sys.stderr.flush()
        return {"ok": False, "error": str(e)}

    if not isinstance(res, dict):
        res = {"ok": True, "text": str(res)}

    thoughts = str(res.get("thoughts") or "")
    text = str(res.get("text") or "")
    usage_val = res.get("usage")
    usage = usage_val if isinstance(usage_val, dict) else {}

    if thoughts:
        sys.stderr.write(markers.llm_thought(call_id, thoughts) + "\n")
    if text:
        sys.stderr.write(markers.llm_delta(call_id, text) + "\n")
    sys.stderr.write(markers.llm_end(call_id, usage=usage) + "\n")
    sys.stderr.flush()

    if raw:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

    return res
