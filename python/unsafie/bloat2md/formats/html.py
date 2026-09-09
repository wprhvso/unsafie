import re
from typing import Final

from lxml import html
from lxml.etree import HTMLParser, ParserError, tostring
from markdownify import markdownify

from unsafie.bloat2md.domain import ConversionError, Payload
from unsafie.bloat2md.sanitize import clean

_STRIPPED: Final = ("script", "style", "noscript", "template", "head", "svg")
_HIDDEN_STYLE: Final = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?!\.[1-9])",
    re.IGNORECASE,
)
_PARSER: Final = HTMLParser(remove_comments=True, remove_pis=True, no_network=True, huge_tree=False)


def _prune(root: html.HtmlElement) -> int:
    dropped = 0
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        style = element.get("style") or ""
        hidden = element.tag in _STRIPPED or (
            bool(style) and _HIDDEN_STYLE.search(style) is not None
        )
        if not hidden and element.get("hidden") is None:
            continue
        parent = element.getparent()
        if parent is None:
            continue
        parent.remove(element)
        dropped += 1
    return dropped


def _promote_headers(root: html.HtmlElement) -> None:
    for table in root.iter("table"):
        if table.find(".//th") is not None:
            continue
        first = table.find(".//tr")
        if first is None:
            continue
        for element in first.findall("td"):
            element.tag = "th"


def to_markdown(source: str) -> tuple[str, int]:
    try:
        root = html.fromstring(source, parser=_PARSER)
    except ParserError as error:
        raise ConversionError("the document could not be parsed as html") from error

    dropped = _prune(root)
    _promote_headers(root)
    body = markdownify(
        tostring(root, encoding="unicode", method="html"),
        heading_style="ATX",
        strip=["a"],
    )
    return clean(body).text, dropped


def convert(raw: bytes) -> Payload:
    markdown, dropped = to_markdown(raw.decode("utf-8", "replace"))
    return Payload(markdown=markdown, dropped={"hidden_nodes": dropped} if dropped else {})
