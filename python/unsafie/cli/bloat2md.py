import asyncio
import sys
from pathlib import Path
from typing import Any

from unsafie.bloat2md import SandboxTimeout, UnsupportedFile, convert, run_isolated


def run(
    path: str,
    *,
    output: str | None = None,
    images_dir: str | None = None,
    to_stdout: bool = False,
    max_pages: int = 50,
    no_sandbox: bool = False,
) -> dict[str, Any]:
    try:
        if path == "-":
            raw = sys.stdin.buffer.read()
            filename = "stdin"
        else:
            target = Path(path)
            if not target.is_file():
                return {"ok": False, "error": f"file not found: {path}"}
            raw = target.read_bytes()
            filename = target.name

        if not raw:
            return {"ok": False, "error": "file is empty"}

        if no_sandbox:
            kind_enum, payload = convert(raw, filename)
            kind = kind_enum.value
        else:
            kind, payload = asyncio.run(run_isolated(raw, filename))

        saved_images: list[str] = []
        if images_dir and payload.images:
            img_dir = Path(images_dir)
            img_dir.mkdir(parents=True, exist_ok=True)
            base_stem = Path(filename).stem
            for idx, img in enumerate(payload.images, start=1):
                ext = "jpg" if "jpeg" in img.mime else "png"
                img_path = img_dir / f"{base_stem}_page_{idx}.{ext}"
                img_path.write_bytes(img.data)
                saved_images.append(str(img_path))

        if to_stdout:
            sys.stdout.write(payload.markdown)
            if not payload.markdown.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
            md_file = None
        elif output:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(payload.markdown, encoding="utf-8")
            md_file = str(out_path)
        else:
            if path == "-":
                out_path = Path("output.md")
            else:
                out_path = Path(path).with_suffix(".md")
            out_path.write_text(payload.markdown, encoding="utf-8")
            md_file = str(out_path)

        res: dict[str, Any] = {
            "ok": True,
            "kind": kind,
            "pages": payload.pages,
            "chars": len(payload.markdown),
            "truncated": payload.truncated,
            "dropped": payload.dropped,
        }
        if md_file:
            res["markdown_file"] = md_file
        if saved_images:
            res["images"] = saved_images
        return res
    except UnsupportedFile as e:
        return {"ok": False, "error": "unsupported", "detail": str(e)}
    except SandboxTimeout as e:
        return {"ok": False, "error": "timeout", "detail": str(e)}
    except Exception as e:
        return {"ok": False, "error": "conversion_failed", "detail": str(e)}
