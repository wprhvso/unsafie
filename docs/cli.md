# unsafie-cli

Один бинарь, которым пользуются и человек, и агент. На машине в пуле он предустановлен и
уже авторизован; на своём ноутбуке ставится и авторизуется в две команды.

```bash
uv tool install unsafie-cli
unsafie auth login --token uns_…      # токен выдаёт бот командой /auth
unsafie help
```

## Как устроена помощь

```
unsafie help                 группы команд одной строкой
unsafie help chrome          группа целиком, с примерами
unsafie chrome shot --help   одна команда: аргументы, флаги, коды возврата
unsafie help --json          весь индекс команд одним ответом — это читает модель
unsafie help tour            первые десять минут
unsafie help markers         структурный вывод
unsafie help exit-codes      коды возврата
```

## Группы

| группа | о чём |
|---|---|
| `meta` | help, version, config, doctor, update, completion |
| `auth` | токены от `/auth`, `me`, `quota` |
| `chat` | say, file, album, edit, rm, react, pin, poll, dice, note, progress, history, chat info/ban/mute/invite |
| `pages` | публикация длинных ответов страницами |
| `github` | account, repo (включая clone с готовыми креденшелами), token, api, gh passthrough |
| `ci` | добавить репозиторий на пул, статус, логи, snippet |
| `machines` | take, release, run, fan, cp, job, term |
| `store` | blob, kv, secret |
| `chrome` | настоящий Chrome на машине: goto, click, type, shot, text, md, eval, tabs, tap, desktop |
| `automation` | schedule, watch, sub, tz, fetch, fs |
| `admin` | доноры, ёмкость, машины, квоты, CI — под токеном оператора |

## Структурный вывод

Команды печатают текст. То, что вызвавший должен увидеть не текстом, уезжает одной строкой:

```
::unsafie::{"kind":"image","blob":"shots/a1b2","mime":"image/png"}
```

Сервер вырезает такие строки и превращает их в картинки внутри результата инструмента,
файлы в чате и заметки в живом логе. Виды: `image`, `file`, `note`, `link`, `sent`,
`result`, `progress`, `error`.

## Настройки

Порядок: флаг, переменная окружения, `~/.config/unsafie/config.toml`, значение по умолчанию.

| ключ | переменная | что это |
|---|---|---|
| `token` | `UNSAFIE_TOKEN` | токен, выданный `/auth` |
| `api` | `UNSAFIE_API` | адрес сервера |
| `chat` | `UNSAFIE_CHAT` | в какой чат писать |
| `machine` | `UNSAFIE_MACHINE` | на какой машине работать |
| `format` | `UNSAFIE_FORMAT` | `text` или `json` |
| `admin` | `UNSAFIE_ADMIN_TOKEN` | токен оператора для группы `admin` |

## Коды возврата

`0` сделано · `1` не вышло · `2` неверный вызов · `3` нет токена или прав · `4` не найдено ·
`5` упёрлись в лимит · `69` команда есть, но ещё не реализована.
