#!/usr/bin/env bash
#
# Слияние ветки задачи: слить, прогнать проверки на результате, закоммитить только
# зелёное.
#
#   scripts/merge-task-branch.sh task/UI-93 -m "merge(область): что изменилось (UI-93)"
#   scripts/merge-task-branch.sh --continue      # после разбора конфликтов руками
#
# Зачем: у слияния два зелёных родителя не означают зелёного результата. Каждая ветка
# прогоняла проверки на своём дереве, а базой для следующей задачи становится результат,
# которого не проверял никто. Живой случай, ради которого заведён этот скрипт (UI-93):
# три ветки, зелёные каждая у себя, дали после чистого слияния четыре падения и сорок
# четыре незапущенных сценария в `pnpm e2e` — и ни то, ни другое не было видно ни в одной
# ветке. Правило целиком — `docs/CONVENTIONS.md`, раздел «Слияние ветки задачи в main».
#
# Второе, что закрывает этот скрипт: раньше слияние проверяли руками, и вывод дважды
# обрезали хвостом, из-за чего красный прогон выглядел законченным. Скрипт сам печатает
# исход и сам отказывается коммитить красное — спутать «мы не дочитали» с «прошло» здесь
# нечем.
#
# Отличие от бэкенда (`../tracker/scripts/merge-task-branch.sh`, `TRK-45`): там один набор
# и один контейнер. Здесь их два, и они разной цены: `pnpm check` идёт на хосте и занимает
# секунды, `pnpm e2e` поднимает контур в Docker и идёт минутами. Оба обязательны — именно
# `pnpm e2e` поймал живой случай выше, `pnpm check` его не увидел бы вовсе, — но дорогой
# набор не запускается вслепую: сперва дешёвый `pnpm check`, и красный останавливает
# слияние, не тратя минуты на Docker. Строка-доказательство называет исход обоих, а не
# только последнего запущенного.

set -euo pipefail

#: Строка-доказательство в сообщении коммита слияния. По ней же считается ревизия
#: непроверенных слияний, поэтому ключ не меняется молча — то же имя стоит
#: в `docs/CONVENTIONS.md` и `README.md`, и сверяет их `testing/merge-script.test.ts`.
TRAILER_KEY="Merge-verified"

#: Дешёвый набор: формат, линт, типы, границы слоёв, модульные и страничные тесты —
#: на хосте, без Docker. Красный останавливает слияние до `E2E_COMMAND`.
CHECK_COMMAND=(pnpm check)

#: Дорогой набор: Playwright против настоящего бэкенда в Docker. Тот же набор, который
#: протокол задачи требует перед обычным коммитом (`docs/CONVENTIONS.md`, «Протокол
#: выполнения задачи») — слияние проверяется по той же планке, по которой проверяли ветки.
E2E_COMMAND=(pnpm e2e)

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
Слияние ветки задачи с прогоном проверок на результате.

  scripts/merge-task-branch.sh <ветка> [-m <сообщение>]
  scripts/merge-task-branch.sh --continue

  <ветка>            что сливать в текущую ветку, обычно task/UI-42
  -m, --message      сообщение коммита слияния целиком; без него берётся то,
                     что предложил git
  --continue         продолжить слияние, конфликты которого разобраны руками:
                     прогнать проверки и закоммитить
  -h, --help         эта справка

Проверки идут на смёрженном дереве до коммита слияния: сперва `pnpm check` (хост,
секунды), затем, если он зелёный, `pnpm e2e` (Docker, минуты). Зелёные оба — коммит со
строкой Merge-verified: и исходом каждого. Красный любой — git merge --abort, ветка
остаётся прежней.

Своя изоляция контура (свой compose-проект, свой порт, свой COMPOSE_FILE) — той же
переменной, какой её задают для прямого `pnpm e2e`: скрипт ничего не подставляет сам,
он лишь запускает `pnpm e2e` в унаследованном окружении.
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
    say "==> ВНИМАНИЕ: слияния без строки ${TRAILER_KEY}: — проверки на их результате не прогоняли"
    printf '%s' "$unverified"
    say "    Это база, поверх которой ляжет текущее слияние."
}

# --- Прогон проверок -------------------------------------------------------------------

#: Итоговые строки двух прогонов, для вывода человеку и для сообщения коммита.
CHECK_SUMMARY=""
E2E_SUMMARY=""

# Последняя содержательная строка вывода — используется, когда у набора нет своей единой
# строки-итога (прогон упал раньше, чем до неё дошло: формат, линт, типы или границы
# слоёв в `pnpm check`).
last_line_of() {
    grep -v '^[[:space:]]*$' "$1" | tail -1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

# Итог `pnpm check`: строка vitest «Tests  N failed | M passed (K)» или «Tests  N passed
# (N)» — она одна и уже содержит и упавшие, и прошедшие, срезать нечего.
summary_of_check() {
    local line
    line="$(grep -E '^[[:space:]]*Tests[[:space:]]' "$1" | tail -1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -n "$line" ] || line="$(last_line_of "$1")"
    printf '%s' "$line"
}

# Итог `pnpm e2e`: Playwright печатает «упавшие» и «прошедшие» отдельными строками, и
# «прошедшие» стоит последней всегда — даже когда прогон красный. Взять одну последнюю
# строку значило бы повторить ошибку, ради которой заведён этот скрипт: усечённый вывод,
# который выглядит зелёным. Поэтому собираются обе строки, если обе есть.
summary_of_e2e() {
    local failed passed line
    failed="$(grep -E '^[[:space:]]*[0-9]+ (failed|interrupted)[[:space:]]*$' "$1" | tail -1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    passed="$(grep -E '^[[:space:]]*[0-9]+ passed' "$1" | tail -1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    if [ -n "$failed" ] && [ -n "$passed" ]; then
        line="$failed, $passed"
    elif [ -n "$failed" ]; then
        line="$failed"
    elif [ -n "$passed" ]; then
        line="$passed"
    else
        line="$(last_line_of "$1")"
    fi
    printf '%s' "$line"
}

run_check() {
    local log status=0
    log="$(mktemp "${TMPDIR:-/tmp}/merge-task-branch-check.XXXXXX")"
    say "==> прогон на результате слияния: ${CHECK_COMMAND[*]}"
    "${CHECK_COMMAND[@]}" 2>&1 | tee "$log" || status=$?
    CHECK_SUMMARY="$(summary_of_check "$log")"
    rm -f "$log"
    return "$status"
}

run_e2e() {
    local log status=0
    log="$(mktemp "${TMPDIR:-/tmp}/merge-task-branch-e2e.XXXXXX")"
    say "==> прогон на результате слияния: ${E2E_COMMAND[*]}"
    "${E2E_COMMAND[@]}" 2>&1 | tee "$log" || status=$?
    E2E_SUMMARY="$(summary_of_e2e "$log")"
    rm -f "$log"
    return "$status"
}

# Дешёвый набор гонится первым: красный на нём останавливает слияние, не тратя минуты
# Docker на результат, который и так не уедет в историю.
run_the_checks() {
    if ! run_check; then
        say "==> ${CHECK_COMMAND[*]} красный на результате слияния: $CHECK_SUMMARY"
        return 1
    fi
    if ! run_e2e; then
        say "==> ${E2E_COMMAND[*]} красный на результате слияния: $E2E_SUMMARY"
        say "    (${CHECK_COMMAND[*]} был зелёным: $CHECK_SUMMARY)"
        return 1
    fi
    return 0
}

# --- Коммит слияния ------------------------------------------------------------------

# Сообщение из `-m` кладётся в `MERGE_MSG` не только перед коммитом, но и сразу на
# конфликте (см. ветку конфликта ниже) — это то же самое место, которое git сам
# создаёт при конфликте и не трогает до следующего коммита, поэтому оно одно и то же
# переживает выход скрипта и повторный вызов `--continue`. Без `-m` строка ничего не
# делает, и `MERGE_MSG` остаётся тем, что предложил git, — как и раньше.
stage_message() {
    [ -z "$MESSAGE" ] || printf '%s\n' "$MESSAGE" >"$(git rev-parse --git-dir)/MERGE_MSG"
}

commit_the_merge() {
    local msg_file
    msg_file="$(git rev-parse --git-dir)/MERGE_MSG"
    stage_message
    printf '\n%s: %s — %s; %s — %s\n' \
        "$TRAILER_KEY" "${CHECK_COMMAND[*]}" "$CHECK_SUMMARY" \
        "${E2E_COMMAND[*]}" "$E2E_SUMMARY" >>"$msg_file"
    # `--cleanup=strip` — иначе комментарии `# Conflicts:`, которые git кладёт в
    # сообщение, уедут в историю: без запуска редактора он их не вычищает.
    git commit --quiet --file="$msg_file" --cleanup=strip
    say "==> слияние закоммичено: $(git log -1 --format='%h %s')"
    say "    ${TRAILER_KEY}: ${CHECK_COMMAND[*]} — ${CHECK_SUMMARY}; ${E2E_COMMAND[*]} — ${E2E_SUMMARY}"
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

    if run_the_checks; then
        commit_the_merge
        exit 0
    fi
    # Здесь, в отличие от обычного хода, `git merge --abort` не делается: он унёс бы
    # разбор конфликтов, стоивший человеку времени. Решает человек.
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

# Неотслеживаемые файлы участвуют в прогоне: `pnpm check` читает дерево как есть, а
# `pnpm e2e` собирает образ из текущего каталога сборки (Docker не разбирает git).
# Лишняя заметка или черновик теста делают исход прогона не свойством слияния.
UNTRACKED="$(git status --porcelain --untracked-files=all | grep '^??' || true)"
[ -z "$UNTRACKED" ] || {
    say "==> ВНИМАНИЕ: в дереве есть неотслеживаемые файлы, прогон увидит и их:"
    printf '%s\n' "$UNTRACKED"
}

report_unverified_merges

say "==> слияние $BRANCH в $(git symbolic-ref --short HEAD) без коммита"
if ! git merge --no-ff --no-commit "$BRANCH"; then
    if git rev-parse --quiet --verify MERGE_HEAD >/dev/null; then
        # Сообщение из `-m` кладётся в `MERGE_MSG` здесь и сейчас: скрипт вот-вот выйдет,
        # а следующий его вызов (`--continue`) о `-m` уже не будет знать ничего — только
        # то, что лежит в `MERGE_MSG`.
        stage_message
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

if run_the_checks; then
    commit_the_merge
    exit 0
fi

git merge --abort
die "слияние отменено, ветка осталась прежней. Красное — свойство слияния, а не веток: чинится задачей, а не повтором"
