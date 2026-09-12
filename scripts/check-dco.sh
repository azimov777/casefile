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

unsigned=""
checked=0

for commit in $commits; do
  checked=$((checked + 1))
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

echo "All ${checked} commit(s) in ${range} are signed off."
