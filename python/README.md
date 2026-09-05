# unsafie — backend

Смотри README в корне репозитория.

```
uv sync
cp .env.example .env
python -m unsafie
```

Приложение само создаёт базу и накатывает миграции при старте.
Фронт (`../svelte/build`) отдаётся nginx'ом; без него Python отдаёт бандл сам.

Трассировка включена по умолчанию и молча выключается, если экспортировать некуда:
`OTEL_ENABLED=0` убирает её совсем, см. [../docs/tracing.md](../docs/tracing.md).
