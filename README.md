# unsafie

Телеграм-бот с агентом внутри и туннель, который ходит через свои же серверы.

```
unsafie/
├── go/                       клиент туннеля: TUN, SOCKS/HTTP-прокси, выбор сервера, мимикрия под Chrome
├── zig/                      экзит: HTTP/1.1 и epoll, без зависимостей; рядом ссылочный nginx
├── android/                  приложение поверх go/ (jni, Compose, самообновление)
├── ansible/                  роль unsafie: systemd, uv, node, два vhost'а
├── fluent/{en,ru}/           тексты: server/ для бэка, web/ для фронта
├── python/unsafie/           бэкенд (FastAPI + aiogram + claude-agent-sdk)
│   ├── app.py settings.py log.py loop.py events.py fluent.py mime.py slugs.py errors.py
│   ├── telemetry/            трассировка: провайдер, спаны, контекст, trace_id в логах
│   ├── database/             модели, репозитории, миграции
│   ├── api/                  routes/{public,admin}, schemas, services, dependencies, static
│   ├── telegram/             manager, sender, render, handlers/, 7 команд
│   ├── github/               app/, webhooks/, client/, ops/, vfs, workspace, cache, bulk
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
- `github.unsafie.com` — только `/gh/webhook`, `/gh/app/new`, `/gh/app/created`.

## Как всё устроено

Каждое сообщение без реплая начинает новый разговор, ответ на любое сообщение продолжает
тот разговор, к которому оно относится. Реакция на ответ бота даёт ссылку на веб-страницу.

GitHub работает по personal access token пользователя (`/gh ТОКЕН`): репозитории, issue,
pull request'ы, actions, поиск, гисты и уведомления — всё этим токеном, включая чужие приватные
репозитории, где пользователь коллаборатор (`/gh add owner/name`). Собственное GitHub App
оставлено только на то, чего токен не умеет: доставку вебхуков и Checks API — прав ему выдаётся
ровно на это, и его installation-токен подхватывает запрос, если токена не хватило. Правки копятся
в виртуальном worktree и уезжают одним коммитом с автоматическим трёхсторонним ребейзом.

Содержимое файлов кэшируется по sha (память + каталог `GITHUB_CACHE_DIR`) — sha неизменяем,
поэтому инвалидация не нужна. Массовое чтение (поиск, дифф) тянет снапшот репозитория одним
архивом вместо запроса на каждый файл.

## Туннель

Клиент зашит на три сервера — `waw`, `de`, `clt` — и решает сам, каким
пользоваться: байесовский выбор с затуханием, классификация отказов по вине
(сервер / экзит / сервис / география / своя же сеть), хеджированные попытки,
phi-accrual и предохранитель. Протокол — [USP/1](docs/protocol.md): две
полудуплексные HTTP-трубы с абсолютными смещениями, поэтому обрыв ноги не рвёт
ни одного соединения внутри туннеля. Как именно выбирается сервер —
[docs/fleet.md](docs/fleet.md).

```
just check-tunnel      # go vet + go test + zig build test
just edge              # поднять экзит локально на 127.0.0.1:8091
just uspcheck          # прогнать через него настоящее соединение
```

Сборка клиентов и деплой экзита приезжают отдельными PR.

Всё, что происходит, попадает в один трейс на событие: от апдейта телеграма до ответа
пользователю, включая время внутри `claude`. Отправляется по OTLP в VictoriaTraces, смотрится
в Grafana, из логов есть переход по `trace_id` — подробности в [docs/tracing.md](docs/tracing.md).
