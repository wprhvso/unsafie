from unsafie_sdk.errors import StopTurn
from unsafie_wire import markers


def stop(message: str | None = None) -> None:
    """Finish the current turn immediately.

    If `message` is provided, sends it to the chat first via `chat.send(message)`.
    """
    if message:
        from unsafie_sdk import chat

        chat.send(message)
    print(markers.stop(message=message), flush=True)
    raise StopTurn(message)
