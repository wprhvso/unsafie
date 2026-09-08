# Третий архив: десктоп

```
tar xzf changes.tar.gz -C /path/to/unsafie
```

Туннель работает — сообщение в браузере пришло от машины через `4409`. Теперь про сам десктоп.

## Почему на машине нет x11vnc

`toolchains._already("xvfb")` спрашивал `any(shutil.which(b) for b in ("Xvfb",))`. На образе
GitHub Actions `Xvfb` предустановлен, поэтому весь apt-набор считался выполненным и
пропускался — а он единственное место, где ставятся `x11vnc`, `openbox`, `xauth`,
`xfonts-base`. В логе job'ы это выглядит как `xvfb: already there`.

Та же дыра была у `tools`: `jq` предустановлен, значит `ripgrep`, `zstd`, `imagemagick`
не ставились никогда.

`PROBES` теперь список групп: внутри группы альтернативы (`google-chrome | chromium`),
но каждая группа обязана быть закрыта. Добавлена `missing(name)` — печатает, чего не хватает.

## Почему дисплея не было вообще

`dial()` звал `vnc.attach()`, а `attach` умеет только повесить x11vnc на **существующий**
дисплей. Пока не отработал `browser.start()`, дисплея нет, и ссылка была мертва по
определению.

Появилась `vnc.ensure()`: если на 5900 никто не слушает — поднимает дисплей сама
(Xkasmvnc, иначе Xvfb + x11vnc + openbox). `dial()` зовёт её. Ссылку теперь можно открыть
до браузера — увидишь пустой рабочий стол, а `browser.start()` подхватит тот же `:97`,
потому что `start_display` сначала проверяет `running(display)`.

Заодно `attach` перестал врать: сообщения теперь `there is no X display on :97` и
`x11vnc is not installed`, вместо одного `no x11vnc and no kasmvnc here` на оба случая.

## Воркфлоу

`.github/workflows/machine.yml` — гвард теперь требует `Xvfb`, `x11vnc` и `openbox` и падает,
если после `setup` их нет. KasmVNC остаётся желательным, но не обязательным.

**Он не применится сам.** Донорские репозитории получают воркфлоу через bootstrap:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://unsafie.com/api/admin/pool/donors/<login>/bootstrap
```

или кнопкой в `/admin/pool`. Пока это не сделано, машины поднимаются по старому файлу.

## Как проверить

1. Прогони bootstrap на донорах, дождись новых машин (keeper поднимет за тик).
2. В логе job'ы шаг `bring the desktop along` должен показать `xvfb: installed`.
3. Открой ссылку `machines.desktop()` — должен появиться openbox без всякого
   `browser.start()`.
