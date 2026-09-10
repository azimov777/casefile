#!/usr/bin/env bash
#
# Слияние ветки задачи: слить, прогнать набор на результате, закоммитить только зелёное.
#
#   scripts/merge-task-branch.sh task/TRK-45 -m "merge(область): что изменилось (TRK-45)"
#   scripts/merge-task-branch.sh --continue      # после разбора конфликтов руками
#
# Зачем: у слияния два зелёных родителя не означают зелёного результата. Каждая ветка
# прогоняла набор у себя, а базой для следующего агента становится результат, которого
# не проверял никто. Правило целиком — `docs/CONVENTIONS.md`, раздел «Слияние ветки
# задачи в main».
#
# Скрипт живёт на хосте, а не в контейнере, потому что ему нужны git и docker: сам
# прогон при этом идёт в контейнере, как и любой другой прогон набора в проекте.

set -euo pipefail

#: Строка-доказательство в сообщении коммита слияния: чем прогнали и что вышло. По ней
#: же считается ревизия непроверенных слияний, поэтому ключ не меняется молча — то же
#: имя стоит в `docs/CONVENTIONS.md` и `README.md`, и сверяет их `tests/test_merge_script.py`.
TRAILER_KEY="Merge-verified"

#: Прогон — тот же, что протокол требует перед коммитом, а не свой облегчённый: слияние
#: проверяется по той же планке, по которой проверяли ветки.
TEST_COMMAND=(docker compose run --rm test)

#: Путь скрипта в репозитории. По коммиту, который его добавил, считается граница
#: ревизии: слияния старше механизма строки не имеют и иметь не могут.
SCRIPT_PATH="scripts/merge-task-branch.sh"

say() { printf '%s\n' "$*"; }
die() {
    printf '%s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'TEXT'
Слияние ветки задачи с прогоном набора на результате.

  scripts/merge-task-branch.sh <ветка> [-m <сообщение>]
  scripts/merge-task-branch.sh --continue

  <ветка>            что сливать в текущую ветку, обычно task/TRK-42
  -m, --message      сообщение коммита слияния целиком; без него берётся то,
                     что предложил git
  --continue         продолжить слияние, конфликты которого разобраны руками:
                     прогнать набор и закоммитить
  -h, --help         эта справка

Набор прогоняется на смёрженном дереве до коммита слияния. Зелёный — коммит со
строкой Merge-verified: и исходом прогона. Красный — git merge --abort, ветка
остаётся прежней.
TEXT
}

# --- Ревизия прошлых слияний ---------------------------------------------------------

# Слияние без строки `Merge-verified:` — это слияние, результат которого никто не
# прогонял. Отказывать из-за него нельзя: строку в готовый коммит уже не вписать, не
# переписав историю. Поэтому такие слияния называются вслух перед каждым следующим —
# пропуск шага виден тому, кто сливает дальше, а не остаётся личным делом пропустившего.
report_unverified_merges() {
    local baseline unverified="" commit
    baseline="$(git log --diff-filter=A --format=%H -- "$SCRIPT_PATH" | tail -1)"
    if [ -z "$baseline" ]; then
        say "==> ревизия слияний пропущена: коммита, добавившего $SCRIPT_PATH, в истории нет"
        return 0
    fi

    while read -r commit; do
        [ -n "$commit" ] || continue
        if ! git log -1 --format=%B "$commit" | grep -q "^${TRAILER_KEY}:"; then
            unverified="$unverified    $(git log -1 --format='%h %s' "$commit")
"
        fi
    done < <(git rev-list --merges "$baseline..HEAD")

    [ -n "$unverified" ] || return 0
    say "==> ВНИМАНИЕ: слияния без строки ${TRAILER_KEY}: — набор на их результате не прогоняли"
    printf '%s' "$unverified"
    say "    Это база, поверх которой ляжет текущее слияние."
}

# --- Прогон набора -------------------------------------------------------------------

#: Последняя строка вывода прогона: «717 passed in 54.92s». Едет в сообщение коммита.
SUITE_SUMMARY=""

summary_of() {
    grep -v '^[[:space:]]*$' "$1" | tail -1 | tr -s '=' ' ' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

run_the_suite() {
    local log status=0
    log="$(mktemp "${TMPDIR:-/tmp}/merge-task-branch.XXXXXX")"
    say "==> прогон набора на результате слияния: ${TEST_COMMAND[*]}"
    # Вывод идёт на экран и в файл разом: человеку нужен ход прогона, сообщению коммита —
    # итоговая строка.
    "${TEST_COMMAND[@]}" 2>&1 | tee "$log" || status=$?
    SUITE_SUMMARY="$(summary_of "$log")"
    rm -f "$log"
    return "$status"
}

# --- Коммит слияния ------------------------------------------------------------------

commit_the_merge() {
    local msg_file
    msg_file="$(git rev-parse --git-dir)/MERGE_MSG"
    [ -z "$MESSAGE" ] || printf '%s\n' "$MESSAGE" >"$msg_file"
    printf '\n%s: %s (%s)\n' "$TRAILER_KEY" "$SUITE_SUMMARY" "${TEST_COMMAND[*]}" >>"$msg_file"
    # `--cleanup=strip` — иначе комментарии `# Conflicts:`, которые git кладёт в
    # сообщение, уедут в историю: без запуска редактора он их не вычищает.
    git commit --quiet --file="$msg_file" --cleanup=strip
    say "==> слияние закоммичено: $(git log -1 --format='%h %s')"
    say "    ${TRAILER_KEY}: ${SUITE_SUMMARY}"
}

# --- Разбор аргументов ---------------------------------------------------------------

BRANCH=""
MESSAGE=""
MODE="merge"

while [ $# -gt 0 ]; do
    case "$1" in
        --continue)
            MODE="continue"
            shift
            ;;
        -m | --message)
            [ $# -ge 2 ] || die "у $1 нет значения"
            MESSAGE="$2"
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        -*) die "неизвестный ключ: $1" ;;
        *)
            [ -z "$BRANCH" ] || die "лишний аргумент: $1"
            BRANCH="$1"
            shift
            ;;
    esac
done

cd "$(git rev-parse --show-toplevel)"

# --- Продолжение после разобранного конфликта ----------------------------------------

if [ "$MODE" = "continue" ]; then
    [ -z "$BRANCH" ] || die "с --continue ветка не нужна: слияние уже начато"
    git rev-parse --quiet --verify MERGE_HEAD >/dev/null ||
        die "начатого слияния нет — сливать нечего"
    [ -z "$(git ls-files --unmerged)" ] ||
        die "остались неразобранные конфликты: разберите их, добавьте в индекс (git add) и повторите"

    if run_the_suite; then
        commit_the_merge
        exit 0
    fi
    # Здесь, в отличие от обычного хода, `git merge --abort` не делается: он унёс бы
    # разбор конфликтов, стоивший человеку времени. Решает человек.
    say "==> набор красный на результате слияния: $SUITE_SUMMARY"
    die "слияние осталось начатым и не закоммичено. Починить и повторить --continue или откатить: git merge --abort"
fi

# --- Обычный ход ---------------------------------------------------------------------

if [ -z "$BRANCH" ]; then
    usage >&2
    die "не названа ветка, которую сливать"
fi
git rev-parse --quiet --verify "${BRANCH}^{commit}" >/dev/null || die "нет такой ветки: $BRANCH"
git symbolic-ref --quiet HEAD >/dev/null || die "HEAD отделён: перейдите на ветку, в которую сливаете"
[ -z "$(git status --porcelain --untracked-files=no)" ] ||
    die "рабочее дерево грязное: слияние проверяется на чистом дереве, иначе прогон видит не то, что уедет в историю"

# Неотслеживаемые файлы монтируются в контейнер вместе с деревом и участвуют в прогоне:
# лишняя заметка или черновик теста делают исход прогона не свойством слияния.
UNTRACKED="$(git status --porcelain --untracked-files=all | grep '^??' || true)"
[ -z "$UNTRACKED" ] || {
    say "==> ВНИМАНИЕ: в дереве есть неотслеживаемые файлы, прогон увидит и их:"
    printf '%s\n' "$UNTRACKED"
}

report_unverified_merges

say "==> слияние $BRANCH в $(git symbolic-ref --short HEAD) без коммита"
if ! git merge --no-ff --no-commit "$BRANCH"; then
    if git rev-parse --quiet --verify MERGE_HEAD >/dev/null; then
        say "==> конфликты: разберите их, добавьте в индекс (git add) и повторите:"
        say "    $SCRIPT_PATH --continue"
        exit 1
    fi
    die "слияние не начато, дерево не тронуто"
fi

if ! git rev-parse --quiet --verify MERGE_HEAD >/dev/null; then
    say "==> сливать нечего: $BRANCH уже в истории"
    exit 0
fi

if run_the_suite; then
    commit_the_merge
    exit 0
fi

say "==> набор красный на результате слияния: $SUITE_SUMMARY"
git merge --abort
die "слияние отменено, ветка осталась прежней. Красное — свойство слияния, а не веток: чинится задачей, а не повтором"
