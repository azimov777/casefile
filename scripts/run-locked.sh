#!/usr/bin/env bash
# Очередь тяжёлых прогонов: одна команда за раз на машину, остальные ждут и печатают, кого и сколько.
#
# Вызов: scripts/run-locked.sh <команда> [аргументы…]
#
# Замок — каталог (mkdir атомарен), вне репозитория: у каждого дерева был бы свой, и очередь не
# была бы общей. В нём файл holder: pid, время взятия, каталог запуска, команда — по строке.
# Переменные: CASEFILE_RUN_LOCK (путь замка, /tmp/casefile-run.lock), CASEFILE_RUN_POLL
# (интервал печати ожидания в секундах, 30), CASEFILE_RUN_MAX_LOAD (порог load average за минуту, 10).
# Скрипт ничего не знает о Docker, pytest и pnpm: он только запускает команду под замком.
set -u

if [ "$#" -eq 0 ]; then
  echo "usage: scripts/run-locked.sh <command> [args...]" >&2
  exit 2
fi

LOCK="${CASEFILE_RUN_LOCK:-/tmp/casefile-run.lock}"
POLL="${CASEFILE_RUN_POLL:-30}"
MAX_LOAD="${CASEFILE_RUN_MAX_LOAD:-10}"
CMD="$*"
START=$(date +%s)
child=""
owned=0

# Сон, который не откладывает сигналы: trap в bash срабатывает после foreground-команды.
nap() {
  sleep "$1" &
  wait $! 2>/dev/null
}

release() {
  # Только свой замок: чужой каталог, взятый другим pid, не трогаем.
  if [ "$owned" = 1 ] && [ "$(sed -n 1p "$LOCK/holder" 2>/dev/null)" = "$$" ]; then
    rm -f "$LOCK/holder"
    rmdir "$LOCK" 2>/dev/null
  fi
  owned=0
}

on_signal() {
  if [ -n "$child" ]; then
    kill -TERM "$child" 2>/dev/null
  fi
  exit "$1"
}

trap release EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM

load_now() {
  if [ -r /proc/loadavg ]; then
    awk '{print $1}' /proc/loadavg
  else
    sysctl -n vm.loadavg | tr -d '{}' | awk '{print $1}'
  fi
}

# --- шаги 2-4: взять замок
waited=0
while :; do
  if mkdir "$LOCK" 2>/dev/null; then
    owned=1
    {
      echo "$$"
      date +%s
      pwd
      echo "$CMD"
    } >"$LOCK/holder"
    break
  fi

  hpid=$(sed -n 1p "$LOCK/holder" 2>/dev/null || true)
  if [ -z "$hpid" ]; then
    # Владелец уже сделал mkdir, но holder ещё не записал: недолго подождать.
    missing=$((${missing:-0} + 1))
    if [ "$missing" -gt 50 ]; then
      echo "stale lock of pid ? removed"
      rm -rf "$LOCK"
      missing=0
    else
      nap 0.1
    fi
    continue
  fi
  missing=0

  if ! kill -0 "$hpid" 2>/dev/null; then
    # Перед удалением убедиться, что за это время замок не взял другой.
    if [ "$(sed -n 1p "$LOCK/holder" 2>/dev/null)" = "$hpid" ]; then
      echo "stale lock of pid $hpid removed"
      rm -rf "$LOCK"
    fi
    continue
  fi

  now=$(date +%s)
  htime=$(sed -n 2p "$LOCK/holder" 2>/dev/null || echo "$now")
  hdir=$(sed -n 3p "$LOCK/holder" 2>/dev/null || true)
  hcmd=$(sed -n 4p "$LOCK/holder" 2>/dev/null || true)
  echo "waiting for lock $((now - START))s: held $((now - ${htime:-$now}))s by pid $hpid in $hdir: $hcmd"
  nap "$POLL"
done

# --- шаг 5: дождаться нагрузки
while :; do
  load=$(load_now)
  if awk -v l="$load" -v m="$MAX_LOAD" 'BEGIN{exit !(l < m)}'; then
    break
  fi
  echo "waiting for load $load < $MAX_LOAD, $(($(date +%s) - START))s"
  nap "$POLL"
done

# --- шаги 6-7: запуск
echo "running: $CMD"
nice -n 15 "$@" <&0 &
child=$!
wait "$child"
code=$?
child=""
echo "RUN_EXIT=$code"
exit "$code"
