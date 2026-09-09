import sys

from unsafie_wire import markers


def stop() -> dict:
    sys.stderr.write(markers.stop() + "\n")
    sys.stderr.flush()
    return {"stopped": True}
