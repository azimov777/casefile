#!/bin/sh
# Режим доступа к установке: кому nginx отдаёт `/config.json` с ключом и каким `Host`
# вообще отвечает (`docs/CONCEPT.md` бэкенда, 5.4; решение TRK-90#5–#7).
#
# Запускает его штатный вход образа nginx, как и `config-json.sh`: номер 30 — после
# `20-envsubst-on-templates.sh`, который развернул шаблон, и до старта сервера. Шаблон
# (`nginx.conf.template`) подключает два файла, которые пишет этот шаг, — поэтому шаг
# обязан отработать всегда, в любом режиме: без файлов nginx не поднимется вовсе.
#
# Два режима, и выбирает их контур, а не образ:
#
# - без пароля (`TRACKER_UI_LOGIN` пуст) — локальная установка: ключ отдаётся без входа, а
#   отвечает nginx только адресам петли (UI-107). Порт при этом обязан быть опубликован
#   на петле (`TRACKER_UI_BIND`): иначе ключ набора `main` получил бы всякий в сети, кто
#   пришлёт `Host: localhost`, — от `curl` проверка `Host` не защищает;
# - с паролем (`TRACKER_UI_LOGIN=password`) — ключ отдаётся только после входа: nginx
#   спрашивает API (`auth_request` на `GET /api/v1/session`), жив ли сеанс из куки, а
#   без сеанса отвечает `401 {"login":"password"}` — по нему интерфейс рисует форму
#   пароля. Проверки `Host` нет: границу держит кука, а сервер отвечает любому своему
#   имени и за любым прокси.
set -eu

dir=/etc/nginx/casefile
login=${TRACKER_UI_LOGIN:-}
bind=${TRACKER_UI_BIND:-127.0.0.1}

mkdir -p "$dir"

case $login in
  password)
    cat >"$dir/host-guard.conf" <<'CONF'
# Режим пароля: проверки Host нет, границу держит кука сеанса (access-mode.sh).
CONF
    cat >"$dir/config-guard.conf" <<'CONF'
auth_request /_casefile/session;
error_page 401 = @login_required;
CONF
    echo "$0: password login is on: /config.json is served after a password login only"
    ;;
  '')
    case $bind in
      127.* | ::1 | '[::1]' | localhost) ;;
      *)
        # Отказ подняться, а не тихий запуск: работающий интерфейс здесь раздавал бы
        # ключ установки всей сети. Сообщение по-английски — его читает владелец
        # установки в `docker compose logs ui`, как и README.
        echo "$0: the board is published on $bind, not on this machine only, and the installation has no owner password." >&2
        echo "$0: refusing to start: it would hand the installation key to anyone who can reach the port." >&2
        echo "$0: set TRACKER_PASSWORD_HASH (python -m app.cli password-hash) or CASEFILE_BIND=127.0.0.1; see README, Network mode." >&2
        exit 1
        ;;
    esac
    cat >"$dir/host-guard.conf" <<'CONF'
# Локальная установка: отвечать только адресам петли (UI-107, nginx.conf.template).
if ($host !~* '^(localhost|127\.0\.0\.1|\[?::1\]?)$') {
    return 421;
}
CONF
    cat >"$dir/config-guard.conf" <<'CONF'
# Локальная установка: ключ отдаётся без входа.
CONF
    ;;
  *)
    echo "$0: TRACKER_UI_LOGIN must be empty or 'password'; refusing to guess the mode" >&2
    exit 1
    ;;
esac
