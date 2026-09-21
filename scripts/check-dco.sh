#!/usr/bin/env bash
#
# Проверка подписи вклада: каждый коммит диапазона несёт `Signed-off-by` своего автора.
#
#   scripts/check-dco.sh                 # ветка задачи против main
#   scripts/check-dco.sh main..HEAD      # явный диапазон
#   scripts/check-dco.sh <base> <head>   # так её зовёт конвейер: две точки PR
#
# Зачем это вообще есть: подпись — единственное доказательство, что автор имел право
# отдать этот код, и что он отдал его под лицензию проекта (`.github/DCO`,
# `CONTRIBUTING.md`). Без неё чужой вклад нельзя ни принять спокойно, ни пересмотреть
# лицензию ядра потом, не спрашивая каждого автора поимённо (TRK-89).
#
# Почему проверяется совпадение с автором, а не просто наличие строки: подпись — это
# заявление конкретного человека о конкретном коде. Строка `Signed-off-by` с чужим
# адресом такого заявления не делает, а выглядит ровно так же.
#
# Слияния пропускаются: у merge-коммита нет своего содержимого, подписывать в нём нечего,
# а делает их не вкладчик, а тот, кто ведёт слияния (`docs/CONVENTIONS.md`).
#
# Dependabot тоже пропускается, но не по имени в коммите — оно ничем не отличается от
# `Signed-off-by` по подделываемости: в коммит можно вписать любое имя и любой адрес, и
# проверка, поверившая ему, перестала бы что-либо значить для всех остальных. Пропуск
# смотрит на `PR_AUTHOR_LOGIN` — кого автором PR считает сам GitHub
# (`.github/workflows/dco.yml`, `github.event.pull_request.user.login`). Это поле GitHub
# выставляет по факту авторизации при открытии PR, и переписать его содержимым вклада
# нельзя: открыть PR от имени `dependabot[bot]` может только сам бот. Переменная пуста при
# локальном запуске человеком — тогда пропуска нет и проверка идёт как обычно.
# `is_dependabot_commit` ниже — вторая, узкая половина признака: даже внутри PR, который
# GitHub числит за ботом, пропускаются только коммиты, которые сам бот и написал —
# `.github/dependabot.yml` правит только lock-файл и своего кода не добавляет.
#
# Скрипт живёт на хосте, а не в контейнере: ему нужна история git, а не окружение
# приложения. Тем же файлом проверку гоняет и конвейер (`.github/workflows/dco.yml`), и
# человек у себя до отправки PR — как и с остальными проверками проекта.

set -euo pipefail

case $# in
  0) range="main..HEAD" ;;
  1) range="$1" ;;
  2) range="$1..$2" ;;
  *)
    echo "usage: scripts/check-dco.sh [<range> | <base> <head>]" >&2
    exit 2
    ;;
esac

commits=$(git rev-list --no-merges "$range")

if [ -z "$commits" ]; then
  echo "No commits to check in $range."
  exit 0
fi

# Кого GitHub считает автором PR — см. блок про Dependabot в шапке файла. Пусто при
# локальном запуске: тогда исключения ниже никогда не сработают.
pr_author_login="${PR_AUTHOR_LOGIN:-}"

is_dependabot_commit() {
  # Имя и адрес коммита сами по себе не доказывают ничего (см. шапку файла) — отсюда и
  # два условия сразу, и то, что вызывающий код проверяет их только вместе с
  # pr_author_login, никогда не вместо него.
  [ "$(git show -s --format='%an' "$1")" = "dependabot[bot]" ] || return 1
  git show -s --format='%ae' "$1" | grep -qE '^[0-9]+\+dependabot\[bot\]@users\.noreply\.github\.com$'
}

unsigned=""
checked=0
exempt=0

for commit in $commits; do
  checked=$((checked + 1))

  if [ "$pr_author_login" = "dependabot[bot]" ] && is_dependabot_commit "$commit"; then
    exempt=$((exempt + 1))
    continue
  fi

  author=$(git show -s --format='%an <%ae>' "$commit")
  # `%(trailers:key=Signed-off-by,valueonly)` разбирает подвал по правилам git, а не
  # грепом: так не считается за подпись строка из тела сообщения или из цитаты.
  signatures=$(git show -s --format='%(trailers:key=Signed-off-by,valueonly)' "$commit")

  if ! printf '%s\n' "$signatures" | grep -qixF "$author"; then
    subject=$(git show -s --format='%s' "$commit")
    short=$(git show -s --format='%h' "$commit")
    unsigned="${unsigned}  ${short} ${subject}
    author:    ${author}
    sign-off:  ${signatures:-(none)}
"
  fi
done

if [ -n "$unsigned" ]; then
  cat >&2 <<MESSAGE
These commits are missing a Signed-off-by line matching their author:

${unsigned}
Every commit must carry the sign-off of the person who wrote it. It certifies that you
have the right to submit the code under the project's licence — the full text is in
.github/DCO.

To sign the commits you already made, rewrite the branch and force-push:

  git rebase --signoff ${range%%..*}

Or, if it is only the last commit:

  git commit --amend -s --no-edit

And from now on, pass -s when you commit:

  git commit -s -m "fix(tasks): ..."
MESSAGE
  exit 1
fi

if [ "$exempt" -gt 0 ]; then
  echo "All ${checked} commit(s) in ${range} are signed off (${exempt} exempt as dependabot[bot])."
else
  echo "All ${checked} commit(s) in ${range} are signed off."
fi
