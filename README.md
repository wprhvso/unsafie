# unsafie

Телеграм-бот с агентом внутри: работает с GitHub, серверами по SSH, расписанием и веб-админкой.

```
unsafie/
├── ansible/                  роль unsafie: systemd, uv, node, два vhost'а
├── fluent/{en,ru}/           тексты: server/ для бэка, web/ для фронта
├── python/unsafie/           бэкенд (FastAPI + aiogram + claude-agent-sdk)
│   ├── app.py settings.py log.py loop.py events.py fluent.py mime.py slugs.py errors.py
│   ├── database/             модели, репозитории, миграции
│   ├── api/                  routes/{public,admin}, schemas, services, dependencies, static
│   ├── telegram/             manager, sender, render, handlers/, 7 команд
│   ├── github/               app/, webhooks/, client/, ops/, vfs, workspace, subscriptions
│   ├── ssh/                  keys, pool, watches, watchdog
│   ├── scheduler/            cron, when, service, runner
│   └── agent/                runtime, turns, prompt/, tools/{tg,gh,ssh,http} — 108 инструментов
└── svelte/                   SvelteKit SPA: share, login, админка на 15 разделов
```

## Запуск

```
cd python && uv sync && cp .env.example .env   # DB_*, ADMIN_TOKEN, *_BASE_URL
cd ../svelte && npm ci && npm run build
cd ../python && python -m unsafie              # база создаётся и мигрируется сама
```

Деплой на VPS — `ansible-playbook site.yml --tags unsafie-deploy`, см. `ansible/README.md`.

## Домены

- `unsafie.com` — SPA, `/{SLUG}` шеринг ответов, `/api/*` админка.
- `github.unsafie.com` — только `/gh/webhook`, `/gh/oauth`, `/gh/app/new`, `/gh/app/created`.

## Как всё устроено

Каждое сообщение без реплая начинает новый разговор, ответ на любое сообщение продолжает
тот разговор, к которому оно относится. Реакция на ответ бота даёт ссылку на веб-страницу.

GitHub работает через собственное GitHub App: репозиторные операции идут installation-токеном,
поиск, гисты, уведомления и создание репо — user-токеном из OAuth. Уведомления приходят
вебхуками. Правки копятся в виртуальном worktree и уезжают одним коммитом с автоматическим
трёхсторонним ребейзом.
