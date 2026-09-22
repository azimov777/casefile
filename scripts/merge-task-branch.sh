#!/usr/bin/env bash
#
# Слияние ветки задачи: слить, пересобрать образ из смёрженного дерева, прогнать набор,
# линтер и (если ветка трогает `ui/`) проверки интерфейса на результате, закоммитить
# только зелёное.
#
#   scripts/merge-task-branch.sh task/TRK-45 -m "merge(область): что изменилось (TRK-45)"
#   scripts/merge-task-branch.sh --continue      # после разбора конфликтов руками
#
# Зачем: у слияния два зелёных родителя не означают зелёного результата. Каждая ветка
# прогоняла набор у себя, а базой для следующего агента становится результат, которого
# не проверял никто. Правило целиком — `docs/CONVENTIONS.md`, раздел «Слияние ветки
# задачи в main».
#
# Скрипт живёт на хосте, а не в контейнере, потому что ему нужны git, docker и (для
# веток, трогающих `ui/`) pnpm: сам прогон бэкенда при этом идёт в контейнере, как и
# любой другой прогон набора в проекте, а `pnpm check` — на хосте, как и в
# `ui/scripts/merge-task-branch.sh`.
#
# Пересборка образа перед прогоном (TRK-70): `docker compose run` берёт уже собранный
# образ и сам его не пересобирает. Без этого шага ветка, меняющая `uv.lock` или
# `docker/Dockerfile.dev`, проверялась бы зависимостями, поставленными в образ до
# слияния, а строка `Merge-verified:` уходила бы в историю неправдой. Пересборка идёт
# тем же `docker compose`, что и сам прогон, — так подхватываются унаследованные
# `COMPOSE_PROJECT_NAME` и `COMPOSE_FILE` вызывающего, а не жёстко названный тег образа.
# Она трогает только образ службы `test`: работающие службы установки (`api`, `mcp`)
# не пересоздаются — решение о них принимает человек, а не скрипт слияния. Тот же образ
# (`image: tracker-dev:latest`, общий у всех служб `docker-compose.yml`) использует и
# служба `lint` — отдельной пересборки под неё не нужно.
#
# Линтер и `pnpm check` (TRK-117, решение владельца в TRK-110): скрипт гонял только
# pytest, и три подряд зелёных слияния (TRK-103, TRK-81, TRK-82) уехали в `main` с
# ошибками `ruff` и непрогнанным `prettier`, пойманными только конвейером GitHub Actions
# на уже опубликованном коммите (TRK-109). `docker compose run --rm lint` (ruff check +
# ruff format --check) гоняется на каждой ветке безусловно — конфиг ruff читает весь
# репозиторий, включая `ui/`. `pnpm check` — только если сама ветка (а не смёрженное
# дерево, где `ui/` есть всегда) трогает `ui/`: он идёт на хосте и требует Node рядом с
# Docker-контуром бэкенда, а большинство веток очереди TRK каталог `ui/` не касаются.
# Сквозные `pnpm e2e` в этот скрипт осознанно не добавлены — они остаются за
# `ui/scripts/merge-task-branch.sh`, которым сливают ветки очереди UI.

set -euo pipefail

#: Строка-доказательство в сообщении коммита слияния: чем прогнали и что вышло. По ней
#: же считается ревизия непроверенных слияний, поэтому ключ не меняется молча — то же
#: имя стоит в `docs/CONVENTIONS.md` и `docs/DEVELOPMENT.md`, и сверяет их `tests/test_merge_script.py`.
TRAILER_KEY="Merge-verified"

#: Прогон — тот же, что протокол требует перед коммитом, а не свой облегчённый: слияние
#: проверяется по той же планке, по которой проверяли ветки.
TEST_COMMAND=(docker compose run --rm test)

#: Линтер бэкенда — та же команда, что `ci.yml` вызывает шагом `Lint`. Гоняется всегда,
#: не только когда правится `app/`: `docker-compose.yml` монтирует репозиторий целиком,
#: и ruff видит весь его, включая `ui/` (TRK-109, TRK-117).
LINT_COMMAND=(docker compose run --rm lint)

#: Проверки интерфейса — та же команда, что `ci.yml` вызывает шагом `Check` в `ui/`
#: (format, eslint, tsc, границы FSD, тесты). Гоняется только если сама ветка трогает
#: `ui/` — решение владельца по TRK-110. Сквозные `pnpm e2e` сюда не входят: они остаются
#: за `ui/scripts/merge-task-branch.sh`.
CHECK_COMMAND=(pnpm check)

#: Пересборка образа службы `test` из смёрженного дерева, до прогона. Названа тем же
#: `docker compose`, что и TEST_COMMAND, и той же службой — драйф между ними ловит
#: `tests/test_merge_script.py`. Служба `lint` пересборки не требует отдельно: она
#: делит один и тот же образ (`image: tracker-dev:latest`) со службой `test`.
BUILD_COMMAND=(docker compose build test)

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

Образ пересобирается из смёрженного дерева, и на нём прогоняются линтер и набор — до
коммита слияния; если сама ветка трогает ui/, следом идёт pnpm check (на хосте, без
Docker). Зелёное всё — коммит со строкой Merge-verified: и исходом каждого прогона.
Красный любой (в том числе неудачная пересборка) — git merge --abort, ветка остаётся
прежней.
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

# --- Прогон набора, линтера и (условно) проверок интерфейса --------------------------

#: Итоговые строки прогонов, для вывода человеку и для сообщения коммита. Пустая
#: `CHECK_SUMMARY` при `RAN_CHECK=0` — сама по себе сигнал «ветка не трогала ui/, pnpm
#: check не запускался», а не забытое присвоение.
LINT_SUMMARY=""
SUITE_SUMMARY=""
CHECK_SUMMARY=""
RAN_CHECK=0

summary_of() {
    grep -v '^[[:space:]]*$' "$1" | tail -1 | tr -s '=' ' ' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

# Итог `pnpm check`: строка vitest «Tests  N failed | M passed (K)» или «Tests  N passed
# (N)» — она одна и уже содержит и упавшие, и прошедшие. Без неё (упал раньше — формат,
# eslint, tsc, границы FSD) берётся последняя содержательная строка вывода, как у
# `summary_of`.
summary_of_check() {
    local line
    line="$(grep -E '^[[:space:]]*Tests[[:space:]]' "$1" | tail -1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -n "$line" ] || line="$(summary_of "$1")"
    printf '%s' "$line"
}

run_build() {
    say "==> пересборка образа из смёрженного дерева: ${BUILD_COMMAND[*]}"
    "${BUILD_COMMAND[@]}"
}

run_lint() {
    local log status=0
    log="$(mktemp "${TMPDIR:-/tmp}/merge-task-branch-lint.XXXXXX")"
    say "==> линтер бэкенда на результате слияния: ${LINT_COMMAND[*]}"
    "${LINT_COMMAND[@]}" 2>&1 | tee "$log" || status=$?
    LINT_SUMMARY="$(summary_of "$log")"
    rm -f "$log"
    return "$status"
}

run_test() {
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

# Дифф самой ветки против базы слияния, а не смёрженного дерева: `ui/` в смёрженном
# дереве есть всегда (это часть main), вопрос — что именно принесла ветка. MERGE_HEAD —
# вершина сливаемой ветки, которую `git merge --no-commit` выставляет что при конфликте,
# что без него, и не трогает до коммита: общее место что для обычного хода, что для
# `--continue`, где имени ветки уже нет.
branch_touches_ui() {
    [ -n "$(git diff --name-only HEAD...MERGE_HEAD -- ui/)" ]
}

run_ui_check() {
    local log status=0
    log="$(mktemp "${TMPDIR:-/tmp}/merge-task-branch-ui.XXXXXX")"
    say "==> ветка трогает ui/: ${CHECK_COMMAND[*]}"
    (cd ui && "${CHECK_COMMAND[@]}") 2>&1 | tee "$log" || status=$?
    CHECK_SUMMARY="$(summary_of_check "$log")"
    rm -f "$log"
    return "$status"
}

# Порядок: пересборка раньше всего (TRK-70, иначе линтер и набор идут на образе до
# слияния); линтер раньше набора — он дешевле, и красный останавливает слияние, не
# тратя минуты на pytest; `pnpm check` — последним и только если ветка трогает `ui/`
# (TRK-117): он идёт на хосте, а не в общем с бэкендом контейнере, и большинства веток
# очереди TRK не касается.
run_the_suite() {
    if ! run_build; then
        SUITE_SUMMARY="пересборка образа не удалась: ${BUILD_COMMAND[*]}"
        say "==> ${BUILD_COMMAND[*]} красная на результате слияния: $SUITE_SUMMARY"
        return 1
    fi

    if ! run_lint; then
        say "==> ${LINT_COMMAND[*]} красный на результате слияния: $LINT_SUMMARY"
        return 1
    fi

    if ! run_test; then
        say "==> ${TEST_COMMAND[*]} красный на результате слияния: $SUITE_SUMMARY"
        say "    (${LINT_COMMAND[*]} был зелёным: $LINT_SUMMARY)"
        return 1
    fi

    if branch_touches_ui; then
        RAN_CHECK=1
        if ! run_ui_check; then
            say "==> ${CHECK_COMMAND[*]} красный на результате слияния: $CHECK_SUMMARY"
            say "    (${LINT_COMMAND[*]} и ${TEST_COMMAND[*]} были зелёными)"
            return 1
        fi
    else
        say "==> ветка не трогает ui/: ${CHECK_COMMAND[*]} не запускается"
    fi

    return 0
}

# --- Коммит слияния ------------------------------------------------------------------

# Сообщение из `-m` кладётся в `MERGE_MSG` не только перед коммитом, но и сразу на
# конфликте (см. ветку конфликта ниже) — это то же самое место, которое git сам создаёт
# при конфликте и не трогает до следующего коммита, поэтому оно одно и то же переживает
# выход скрипта и повторный вызов `--continue`. Без `-m` строка ничего не делает, и
# `MERGE_MSG` остаётся тем, что предложил git, — как и раньше.
stage_message() {
    [ -z "$MESSAGE" ] || printf '%s\n' "$MESSAGE" >"$(git rev-parse --git-dir)/MERGE_MSG"
}

commit_the_merge() {
    local msg_file trailer_line ui_part
    msg_file="$(git rev-parse --git-dir)/MERGE_MSG"
    stage_message
    if [ "$RAN_CHECK" -eq 1 ]; then
        ui_part="; ${CHECK_COMMAND[*]} — ${CHECK_SUMMARY}"
    else
        ui_part="; ${CHECK_COMMAND[*]} — ветка не трогает ui/, не запускался"
    fi
    trailer_line="${TRAILER_KEY}: ${LINT_COMMAND[*]} — ${LINT_SUMMARY}; ${TEST_COMMAND[*]} — ${SUITE_SUMMARY}${ui_part}"
    printf '\n%s\n' "$trailer_line" >>"$msg_file"
    # `--cleanup=strip` — иначе комментарии `# Conflicts:`, которые git кладёт в
    # сообщение, уедут в историю: без запуска редактора он их не вычищает.
    git commit --quiet --file="$msg_file" --cleanup=strip
    say "==> слияние закоммичено: $(git log -1 --format='%h %s')"
    say "    $trailer_line"
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
    # разбор конфликтов, стоивший человеку времени. Решает человек. Что именно красное,
    # `run_the_suite` уже назвал.
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

if run_the_suite; then
    commit_the_merge
    exit 0
fi

# Что именно красное, `run_the_suite` уже назвал.
git merge --abort
die "слияние отменено, ветка осталась прежней. Красное — свойство слияния, а не веток: чинится задачей, а не повтором"
