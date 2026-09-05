import logging
from typing import Any

from fluent.runtime import FluentBundle, FluentResource

from unsafie.settings import settings

logger = logging.getLogger(__name__)

_bundles: dict[str, FluentBundle | None] = {}


def _load(locale: str, part: str = "server") -> FluentBundle | None:
    folder = settings.fluent_dir / locale / part
    if not folder.is_dir():
        return None
    bundle = FluentBundle([locale], use_isolating=False)
    for path in sorted(folder.glob("*.ftl")):
        resource = FluentResource(path.read_text(encoding="utf-8"))
        try:
            bundle.add_resource(resource)
        except Exception as e:
            logger.error("fluent %s: %s", path, e)
    return bundle


def bundle(locale: str | None) -> FluentBundle | None:
    locale = locale or settings.default_locale
    if locale not in _bundles:
        _bundles[locale] = _load(locale)
        if _bundles[locale] is None:
            logger.warning("fluent: no locale %s at %s", locale, settings.fluent_dir)
    b = _bundles[locale]
    if b is None and locale != settings.default_locale:
        return bundle(settings.default_locale)
    return b


def reload() -> None:
    _bundles.clear()


def has(key: str, locale: str | None = None) -> bool:
    b = bundle(locale)
    return b is not None and b.has_message(key)


def t(key: str, locale: str | None = None, /, **args: Any) -> str:
    b = bundle(locale)
    if b is None or not b.has_message(key):
        if locale and locale != settings.default_locale:
            return t(key, settings.default_locale, **args)
        logger.error("fluent: missing key %s (locale=%s)", key, locale or settings.default_locale)
        return f"⟨{key}⟩"
    message = b.get_message(key)
    if message.value is None:
        logger.error("fluent: key %s has no value", key)
        return f"⟨{key}⟩"
    text, errors = b.format_pattern(message.value, args)
    for err in errors:
        logger.error("fluent: %s in %s: %s", type(err).__name__, key, err)
    return text


def attr(key: str, name: str, locale: str | None = None, /, **args: Any) -> str:
    b = bundle(locale)
    if b is None or not b.has_message(key) or name not in b.get_message(key).attributes:
        logger.error("fluent: missing attribute %s.%s", key, name)
        return f"⟨{key}.{name}⟩"
    text, errors = b.format_pattern(b.get_message(key).attributes[name], args)
    for err in errors:
        logger.error("fluent: %s in %s.%s: %s", type(err).__name__, key, name, err)
    return text
