# ansible

Роль `unsafie` ставит бота как systemd-сервис рядом с остальными на VPS.

## Что добавить в group_vars/all

```yaml
# vars.yml
domains:
  - "{{ domain }}"
  - "github.{{ domain }}"

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

Роль ожидает, что до неё отработали `postgres` (с `auth_method: trust` для localhost)
и `nginx`.

## Деплой

```
ansible-playbook site.yml --tags unsafie-deploy
```

Тянет репозиторий, синкает зависимости, собирает фронт и перезапускает сервис.
Только конфиг: `--tags unsafie-web`, только юнит: `--tags unsafie-service`.

## TLS и Cloudflare Tunnel

TLS терминируется на краю Cloudflare. На сервере nginx слушает только `:80`,
сертификатов не держит, редиректов на https не делает. Порты 80 и 443 в ufw закрыты,
наружу торчит только `dumbvpn_relay_port` — relay ходит мимо Cloudflare
со своим самоподписанным сертификатом (клиент его не проверяет).

Реальный адрес клиента nginx берёт из `CF-Connecting-IP`, доверяя `127.0.0.1`,
поэтому `$remote_addr` в логах остаётся публичным IP.

Список `domains` из `group_vars/all/vars.yml` разворачивается в `ingress` туннеля:
каждое имя уходит в `http://127.0.0.1:80`, дальше маршрутизирует nginx по `Host`.

### Разовый бутстрап туннеля

```
cloudflared tunnel login
cloudflared tunnel create unsafie.com
```

Из полученного `~/.cloudflared/<UUID>.json` в vault кладутся три значения:

```yaml
# vault.yml
vault_cloudflared_account_tag: "..."     # AccountTag
vault_cloudflared_tunnel_id: "..."       # TunnelID
vault_cloudflared_tunnel_secret: "..."   # TunnelSecret
```

DNS-записи создаются один раз на каждое имя:

```
for h in $(yq '.domains[]' group_vars/all/vars.yml); do
  cloudflared tunnel route dns unsafie.com "$h"
done
```

В зоне появятся `CNAME <host> -> <UUID>.cfargotunnel.com` в режиме proxied.
