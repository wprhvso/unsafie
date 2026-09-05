# unsafie — backend

Смотри README в корне репозитория.

```
uv sync
cp .env.example .env
python -m unsafie
```

Приложение само создаёт базу и накатывает миграции при старте.
Фронт (`../svelte/build`) отдаётся nginx'ом; без него Python отдаёт бандл сам.
