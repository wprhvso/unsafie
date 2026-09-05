# ansible

Роль `unsafie` ставит бота как systemd-сервис рядом с остальными на VPS.

## Что добавить в group_vars/all

```yaml
# vars.yml
domains:
  - "{{ domain }}"
  - "github.{{ domain }}"     # для certbot

# vault.yml
unsafie_admin_token: "..."     # ansible-vault, длинная случайная строка
```

Токен админки генерируется один раз, например `openssl rand -hex 32`, и кладётся в vault.
Смена токена инвалидирует все сессии админки.

## Подключение

```yaml
# site.yml
- role: unsafie
```

Роль ожидает, что до неё отработали `postgres` (с `auth_method: trust` для localhost),
`nginx` и `certbot` — сертификат для `github.{{ domain }}` должен существовать до
первого `nginx -t`, иначе выпусти его вручную и прогони роль ещё раз.

## Деплой

```
ansible-playbook site.yml --tags unsafie-deploy
```

Тянет репозиторий, синкает зависимости, собирает фронт и перезапускает сервис.
Только конфиг: `--tags unsafie-web`, только юнит: `--tags unsafie-service`.
