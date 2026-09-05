# Трассировка

Один трейс — одно событие: сообщение в телеграме, HTTP-запрос, вебхук GitHub, сработавшая
задача, проверка watch. Внутри трейса не должно быть пустых промежутков: каждая секунда
объяснена либо спаном внешнего вызова (БД, GitHub, SSH, Bot API), либо спаном «модель пишет».

Данные уходят по OTLP в [VictoriaTraces](https://docs.victoriametrics.com/victoriatraces/)
(`127.0.0.1:4317`), смотреть — в Grafana, датасорсы `VictoriaTraces` (Jaeger) и
`VictoriaTraces (TraceQL)` (Tempo).

## Как выглядит трейс

```
tg.update                       CONSUMER   апдейт от телеграма — корень
├─ SELECT/INSERT …                         sqlalchemy, автоинструментация
├─ turn.route                              в какой тёрн попадает сообщение
└─ agent.turn                              один ответ агента целиком
   ├─ agent.attempt             #1         попытка с конкретным credential
   │  ├─ agent.context                     сборка системного контекста
   │  └─ gen_ai.invoke_agent    CLIENT     весь query() к claude-agent-sdk
   │     ├─ gen_ai.session.init            старт CLI-субпроцесса
   │     ├─ gen_ai.completion   CLIENT     модель писала ответ
   │     ├─ gen_ai.tool Bash               встроенный инструмент (из hooks)
   │     ├─ tool.gh_fs_read                наш MCP-инструмент
   │     │  ├─ github GET /repos  CLIENT
   │     │  └─ SELECT …
   │     ├─ tool.send_message
   │     │  └─ tg.api sendMessage CLIENT
   │     └─ gen_ai.completion
   └─ tg.send                   PRODUCER   финальный ответ пользователю
```

Другие корни: `GET /api/...` (FastAPI), `gh.webhook push`, `scheduler.task`, `ssh.watch`,
`app.startup` / `app.shutdown`.

## Чем закрыты разрывы

| Разрыв | Чем закрыт |
| --- | --- |
| `query()` уходит в CLI-субпроцесс `claude` | `agent/trace.py`: `Recorder` строит спаны из потока SDK-сообщений (`gen_ai.completion`) и из хуков `PreToolUse`/`PostToolUse` (`gen_ai.tool …`), с явными таймстампами — вместе они покрывают всё время внутри `query()` |
| MCP-инструменты вызываются из тасок SDK | `ToolContext.trace` — `telemetry.Anchor`: попытка запоминает свой контекст, `guarded()` открывает спан инструмента явно от него |
| `asyncio.create_task` для вебхука | своя трасса + `link` на спан HTTP-запроса (ответ GitHub'у уже отправлен) |
| Долгоживущие таски (polling, лупы) | `telemetry.detached()` — стартуют с пустым контекстом, иначе все апдейты навечно стали бы детьми спана запуска |
| Холостые тики лупов | `telemetry.muted()` вокруг опроса БД: тик — не событие, событие — найденная задача |
| Логи и трейсы врозь | `trace=… span=…` в каждой строке (`telemetry/logs.py`), vector поднимает их в поля, Grafana ходит логи ⇄ трейсы |
| nginx и приложение | nginx отдаёт `X-Request-ID` (он же `$request_id` в access-логе), приложение кладёт его в `unsafie.request_id` |

## Соглашения

* **Имена спанов** — низкой кардинальности: `ssh.exec`, `tool.gh_commit`, `github GET /repos`.
  Всё переменное (id, репозиторий, команда) живёт в атрибутах.
* **Kind**: CONSUMER — входящее событие, SERVER — HTTP, CLIENT — исходящий вызов (БД, GitHub,
  SSH, Bot API, модель), PRODUCER — отправка в телеграм, INTERNAL — остальное.
* **Атрибуты** собраны в `telemetry/attrs.py`. Свои — с префиксом `unsafie.`, для агента —
  `gen_ai.*` из [семантических соглашений](https://opentelemetry.io/docs/specs/semconv/gen-ai/).
* **Ошибки**: `OpsError` (отказ, который видит модель: «нет такого файла», недоступный хост) —
  это не сбой, спан остаётся зелёным с `unsafie.refused=true` и `unsafie.refusal`. Красным
  становится только неожиданное исключение. Отмена таски — `unsafie.cancelled=true`.
* **Контент** (промпты, ответы модели, аргументы инструментов) пишется только при
  `OTEL_CAPTURE_CONTENT=1`, всегда обрезается до `OTEL_MAX_ATTR_LEN` и прогоняется через
  вычищение секретов (`attrs.scrub`).

## Настройки

| Переменная | По умолчанию | Смысл |
| --- | --- | --- |
| `OTEL_ENABLED` | `1` | `0` — провайдер не ставится, все `span()` становятся no-op |
| `OTEL_ENDPOINT` | `http://127.0.0.1:4317` | OTLP-эндпоинт (алиас `OTEL_EXPORTER_OTLP_ENDPOINT`) |
| `OTEL_PROTOCOL` | `grpc` | `grpc` или `http/protobuf`; для HTTP путь `/insert/opentelemetry/v1/traces` добавляется сам |
| `OTEL_SAMPLE_RATIO` | `1.0` | доля трейсов; решение родителя не пересматривается |
| `OTEL_CAPTURE_CONTENT` | `0` | писать ли тексты промптов/ответов/аргументов |
| `OTEL_MAX_ATTR_LEN` | `4096` | обрезка длинных атрибутов |
| `SERVICE_NAME` / `SERVICE_VERSION` / `ENVIRONMENT` | `unsafie` / версия пакета / `dev` | ресурсные атрибуты; ansible кладёт в `SERVICE_VERSION` sha задеплоенного коммита |

Батчер: `OTEL_QUEUE_SIZE`, `OTEL_BATCH_SIZE`, `OTEL_SCHEDULE_DELAY` (мс), `OTEL_EXPORT_TIMEOUT`.

## Как этим пользоваться

Новый спан:

```python
from unsafie import telemetry
from unsafie.telemetry import attrs

with telemetry.span("ssh.exec", kind=telemetry.CLIENT, attributes={attrs.SSH_ALIAS: alias}) as s:
    ...
    telemetry.set_attrs(s, {attrs.SSH_EXIT: code})
```

Функция целиком — `@telemetry.traced("github.commit")` плюс `telemetry.annotate(...)` внутри.

Не надо руками трассировать репозитории БД: каждый запрос уже виден благодаря
инструментации SQLAlchemy. И не надо ставить спан там, где он будет срабатывать сотни раз
за операцию (чтение блоба из кеша) — такие вещи учитываются счётчиками
`unsafie.github.requests` / `cache_hits` / `from_snapshot` на спане инструмента.

## Что специально не сделано

* **aiohttp не инструментируется глобально**: `getUpdates` висит по 30 секунд, а
  `sendChatAction` повторяется каждые 5 — вместо этого ручные спаны в
  `telegram/tracing.py` и `github/client/base.py`, где и атрибуты богаче.
* **Метрики и логи по OTLP не отправляются**: логи уже собирает vector в VictoriaLogs,
  метрики — vmagent в VictoriaMetrics.
* **Свою телеметрию `claude` CLI (`CLAUDE_CODE_ENABLE_TELEMETRY`) не включаем**: это метрики
  и логи, а не трейсы; границы его работы мы и так восстанавливаем из хуков.

## Проверка

```
curl -s 'http://127.0.0.1:10428/select/jaeger/api/services'
journalctl -u unsafie -n 50 | grep -o 'trace=[0-9a-f]*' | tail
```

Первый должен вернуть `unsafie`, второй — id, который открывается в Grafana.
