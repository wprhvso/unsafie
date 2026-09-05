import base64

from nacl import encoding, public

from unsafie.github.errors import GithubError


def seal(public_key_b64: str, secret: str) -> str:
    try:
        key = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    except Exception as e:
        raise GithubError(f"bad public key from github: {e}") from e
    sealed = public.SealedBox(key).encrypt(secret.encode())
    return base64.b64encode(sealed).decode()
