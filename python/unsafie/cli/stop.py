import sys

from unsafie.cli import chat
from unsafie_wire import markers


def stop(message: str | None = None) -> dict:
    if message:
        chat.send(message)
    sys.stderr.write(markers.stop(message=message) + "\n")
    sys.stderr.flush()
    return {"stopped": True, "message": message}
