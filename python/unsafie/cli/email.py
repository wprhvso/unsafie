from unsafie.cli.client import client


def get_code(email: str) -> str:
    res = client().call("GET", "/email/code", params={"email": email})
    if isinstance(res, dict):
        return str(res.get("code") or "0")
    if res is not None:
        return str(res)
    return "0"
