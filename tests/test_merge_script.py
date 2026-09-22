"""Скрипт слияния под тестом: его запускают редко и в единственный неудобный момент.

`scripts/merge-task-branch.sh` — единственное место, где проверяется результат слияния
(`docs/CONVENTIONS.md`, раздел «Слияние ветки задачи в main»). Пять вещей ломаются молча
и обнаруживаются ровно тогда, когда сливают ветку и меньше всего хотят разбираться с
инструментом, — их и сторожит этот файл:

- потерянный бит запуска: файл в репозитории есть, а `scripts/merge-task-branch.sh`
  отвечает «Permission denied»;
- опечатка в самом скрипте: `bash -n` ловит её здесь, а не на первом слиянии;
- разъехавшиеся скрипт и документы: строка-доказательство названа в двух документах, по
  ней же скрипт ищет непроверенные слияния, и переименование ключа в одном месте
  оставляет ревизию без единой находки — тихо и навсегда;
- сообщение из `-m` теряется на конфликте (TRK-54, готовое решение — UI-96): скрипт
  выходит подсказкой про `--continue` раньше, чем кладёт `MESSAGE` в `MERGE_MSG`, и
  повторный вызов `--continue` этого сообщения уже не знает — коммит слияния получает
  заголовок, который предложил сам git;
- набор прогоняется на образе, собранном до слияния (TRK-70): `docker compose run` сам
  образ не пересобирает, и ветка, меняющая `uv.lock` или `docker/Dockerfile.dev`,
  получала бы `Merge-verified:` на старых версиях зависимостей;
- линтер бэкенда (`ruff`) и проверки интерфейса (`pnpm check`) не гонялись вовсе
  (TRK-110, TRK-117): три подряд зелёных слияния (TRK-103, TRK-81, TRK-82) уехали в
  `main` с ошибками `ruff` и непрогнанным `prettier`, пойманными только на GitHub
  Actions, когда коммит уже был в истории (TRK-109). Красные `lint`/`pnpm check`
  обязаны останавливать слияние так же, как красный набор, а `pnpm check` — гоняться
  только когда сама ветка (не смёрженное дерево) трогает `ui/`.

Первые три проверки читают скрипт текстом — запускать его отсюда нечем, git и docker
живут на хосте. Остальные ведут на временном git-репозитории: сам
`scripts/merge-task-branch.sh` запускается по-настоящему (git с TRK-54 есть и в
дев-образе), а `docker` и `pnpm` на `PATH` подменены поддельными исполняемыми файлами —
мгновенными и не трогающими ни настоящий Docker, ни настоящий Node, ни настоящий набор.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "merge-task-branch.sh"

#: Документы, описывающие слияние. Оба обязаны звать ту же строку и ту же команду, что
#: и скрипт: расхождение здесь — это правило, которое исполняют по памяти.
DOCUMENTS = (PROJECT_ROOT / "docs" / "CONVENTIONS.md", PROJECT_ROOT / "docs" / "DEVELOPMENT.md")

#: Объявления в шапке скрипта. Читаются текстом, а не запуском: запускать скрипт отсюда
#: нечем, а объявлены они одной строкой именно затем, чтобы их можно было прочитать.
TRAILER_KEY = re.compile(r'^TRAILER_KEY="([^"]+)"', re.MULTILINE)
TEST_COMMAND = re.compile(r"^TEST_COMMAND=\(([^)]+)\)", re.MULTILINE)
LINT_COMMAND = re.compile(r"^LINT_COMMAND=\(([^)]+)\)", re.MULTILINE)
CHECK_COMMAND = re.compile(r"^CHECK_COMMAND=\(([^)]+)\)", re.MULTILINE)
BUILD_COMMAND = re.compile(r"^BUILD_COMMAND=\(([^)]+)\)", re.MULTILINE)


def _declaration(pattern: re.Pattern[str]) -> str:
    """Значение объявления из шапки скрипта."""
    found = pattern.search(SCRIPT.read_text(encoding="utf-8"))
    assert found is not None, f"в скрипте нет объявления {pattern.pattern!r}"
    return found.group(1).strip()


def test_the_script_is_there_and_carries_the_bit_to_run_it() -> None:
    """Бит запуска — часть содержимого файла, а не свойство машины.

    Он хранится в git (`100755`) и теряется ровно один раз — на создании файла. Дальше
    команда из README отвечает «Permission denied» тому, кто сливает ветку.
    """
    assert SCRIPT.is_file(), f"нет файла {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} без бита запуска: в git он хранится как 100755"


def test_the_script_parses() -> None:
    """Опечатка в скрипте обнаруживается здесь, а не на первом слиянии."""
    bash = shutil.which("bash")
    assert bash is not None, "в образе нет bash — проверить синтаксис нечем"
    done = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr


def test_the_documents_name_the_same_proof_line_as_the_script() -> None:
    """Ключ строки-доказательства один на скрипт и на документы.

    По этому ключу скрипт ищет слияния, у которых прогона не было. Переименованный в
    скрипте и оставшийся в документах, он не сломает ничего видимого: ревизия просто
    перестанет находить непроверенные слияния, а документы будут звать искать строку,
    которой больше нет.
    """
    key = _declaration(TRAILER_KEY)
    missing = [
        document.name for document in DOCUMENTS if key not in document.read_text(encoding="utf-8")
    ]

    assert not missing, f"строка {key!r} из скрипта не названа в {missing}"


def test_the_merge_runs_the_whole_suite_and_says_so() -> None:
    """Слияние проверяется той же командой, что и ветка перед коммитом.

    Облегчённый прогон на слиянии — это вторая планка качества, о которой никто не
    договаривался: часть набора зелена, а `main` красный по тому, что решили не гонять.
    Поэтому команда из скрипта обязана быть той же, которую `docs/DEVELOPMENT.md` называет прогоном
    набора.
    """
    command = " ".join(_declaration(TEST_COMMAND).split())
    readme = (PROJECT_ROOT / "docs" / "DEVELOPMENT.md").read_text(encoding="utf-8")

    assert f"`{command}`" in readme, f"docs/DEVELOPMENT.md не называет {command!r} прогоном набора"


def test_the_documents_name_lint_and_pnpm_check_as_merge_steps() -> None:
    """TRK-117: линтер и `pnpm check` — такие же прогоны слияния, как набор, и обязаны
    быть названы там же, где документы называют `TEST_COMMAND` — иначе память того, кто
    сливает ветки, разойдётся со скриптом молча."""
    lint = " ".join(_declaration(LINT_COMMAND).split())
    check = " ".join(_declaration(CHECK_COMMAND).split())
    documents = {
        name: (PROJECT_ROOT / "docs" / name).read_text(encoding="utf-8")
        for name in ("CONVENTIONS.md", "DEVELOPMENT.md")
    }

    for name, text in documents.items():
        assert f"`{lint}`" in text, f"docs/{name} не называет {lint!r} шагом слияния"
        assert f"`{check}`" in text, f"docs/{name} не называет {check!r} шагом слияния"


def test_the_build_command_uses_compose_and_not_a_hardcoded_tag() -> None:
    """Пересборка (TRK-70) идёт тем же `docker compose`, что и прогон, а не `docker build -t`.

    Жёстко названный тег обошёл бы `COMPOSE_PROJECT_NAME`/`COMPOSE_FILE`, унаследованные
    вызывающим (свой compose-проект, свои порты), и пересобрал бы образ чужого контура.
    """
    build = _declaration(BUILD_COMMAND).split()
    assert build[:2] == ["docker", "compose"], f"BUILD_COMMAND не через docker compose: {build!r}"
    assert "build" in build, f"BUILD_COMMAND не вызывает build: {build!r}"


def test_the_build_and_test_commands_name_the_same_service() -> None:
    """`BUILD_COMMAND` и `TEST_COMMAND` обязаны пересобирать и запускать одну службу.

    Разъехавшиеся имена службы — это пересборка образа, который прогон не использует:
    `Merge-verified:` продолжил бы врать так же, как до TRK-70.
    """
    build_service = _declaration(BUILD_COMMAND).split()[-1]
    test_service = _declaration(TEST_COMMAND).split()[-1]
    assert build_service == test_service, (
        f"BUILD_COMMAND называет службу {build_service!r}, TEST_COMMAND — {test_service!r}"
    )


# --- Запуск самого скрипта на временном git-репозитории с поддельным `docker` -------
#
# Дальше идут проверки, которые исполняют сам скрипт, а не читают его текстом: им нужен
# настоящий git. `docker` на `PATH` подменяется поддельным исполняемым файлом —
# мгновенным и не трогающим ни настоящий Docker, ни настоящий набор.


#: Поддельный `docker`: отвечает на `compose build ...` мгновенно и зелёным, а на
#: `compose run --rm lint` и `compose run --rm test` — заданными кодами (по умолчанию
#: оба зелёные, как раньше). Различает их по имени службы — четвёртому аргументу, тому
#: же, что `--rm <служба>` кладёт в `docker compose run --rm <служба>`. Строки вывода
#: подобраны под `summary_of`/`summary_of_check` скрипта (последняя непустая строка) —
#: им всё равно, откуда она, лишь бы была.
def _fake_docker_script(*, lint_exit: int = 0, test_exit: int = 0) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
if [ "${{1:-}}" = compose ] && [ "${{2:-}}" = build ]; then
    exit 0
fi
if [ "${{1:-}}" = compose ] && [ "${{2:-}}" = run ] && [ "${{4:-}}" = lint ]; then
    echo "lint output"
    exit {lint_exit}
fi
if [ "${{1:-}}" = compose ] && [ "${{2:-}}" = run ] && [ "${{4:-}}" = test ]; then
    echo "1 passed in 0.01s"
    exit {test_exit}
fi
echo "поддельный docker не знает команду: $*" >&2
exit 1
"""


def _make_fake_bin(
    tmp_path: Path, *, lint_exit: int = 0, test_exit: int = 0, label: str = "fakebin"
) -> Path:
    """Каталог с поддельным `docker` на `PATH`, впереди настоящего."""
    bin_dir = tmp_path / label
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        _fake_docker_script(lint_exit=lint_exit, test_exit=test_exit), encoding="utf-8"
    )
    fake_docker.chmod(0o755)
    return bin_dir


def _add_fake_pnpm(bin_dir: Path, *, exit_code: int = 0, log: Path | None = None) -> None:
    """Добавляет в уже существующий каталог с поддельным `docker` поддельный `pnpm` —
    тот же приём: мгновенный, не трогает ни Node, ни настоящий `pnpm check`. `log`, если
    задан, получает аргументы каждого вызова — этим ловится сам факт (не)вызова: ветка,
    не трогающая `ui/`, не должна оставить в нём ни строки."""
    fake_pnpm = bin_dir / "pnpm"
    record = f"printf '%s\\n' \"$*\" >>{log}\n" if log is not None else ""
    fake_pnpm.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
{record}if [ "${{1:-}}" = check ]; then
    echo "Tests  1 passed (1)"
    exit {exit_code}
fi
echo "поддельный pnpm не знает команду: $*" >&2
exit 1
""",
        encoding="utf-8",
    )
    fake_pnpm.chmod(0o755)


def _make_fake_bin_recording_invocations(tmp_path: Path, log: Path) -> Path:
    """Как `_make_fake_bin`, но вдобавок дописывает свои аргументы в `log` строкой за
    каждым вызовом — этим и ловится порядок TRK-70: пересборка обязана случиться
    раньше прогона, а не наоборот и не вместо него."""
    bin_dir = tmp_path / "fakebin-recording"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>{log}
if [ "${{1:-}}" = compose ] && [ "${{2:-}}" = build ]; then
    exit 0
fi
if [ "${{1:-}}" = compose ] && [ "${{2:-}}" = run ]; then
    echo "1 passed in 0.01s"
    exit 0
fi
echo "поддельный docker не знает команду: $*" >&2
exit 1
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    return bin_dir


def _git(repo: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _git_output(repo: Path, args: list[str]) -> str:
    done = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _make_repo_with_conflict(tmp_path: Path) -> Path:
    """Временный репозиторий с веткой `task/TRK-0`, конфликтующей с `main` в одной строке
    одного файла: обе ветки меняют её по-своему от общей базы."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, ["init", "--quiet"])
    _git(repo, ["checkout", "--quiet", "-b", "main"])
    _git(repo, ["config", "user.email", "test@example.invalid"])
    _git(repo, ["config", "user.name", "Test"])

    file = repo / "file.txt"
    file.write_text("база\n", encoding="utf-8")
    _git(repo, ["add", "file.txt"])
    _git(repo, ["commit", "--quiet", "-m", "база"])

    _git(repo, ["checkout", "--quiet", "-b", "task/TRK-0"])
    file.write_text("из ветки\n", encoding="utf-8")
    _git(repo, ["add", "file.txt"])
    _git(repo, ["commit", "--quiet", "-m", "из ветки"])

    _git(repo, ["checkout", "--quiet", "main"])
    file.write_text("из main\n", encoding="utf-8")
    _git(repo, ["add", "file.txt"])
    _git(repo, ["commit", "--quiet", "-m", "из main"])

    return repo


def _resolve_conflict(repo: Path) -> None:
    (repo / "file.txt").write_text("разрешено\n", encoding="utf-8")
    _git(repo, ["add", "file.txt"])


def _commit_body(repo: Path) -> str:
    done = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def _run_script(repo: Path, fake_bin: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run([str(SCRIPT), *args], cwd=repo, env=env, capture_output=True, text=True)


def test_the_message_from_dash_m_survives_a_conflict_and_continue(tmp_path: Path) -> None:
    """UI-96: `-m` кладётся в `MERGE_MSG` на конфликте, а не только перед коммитом.

    Без этого повторный вызов `--continue` — уже новый процесс с пустым `$MESSAGE`, и
    коммит слияния получает предложение git («Merge branch …»), а не переданное сообщение.
    """
    git = shutil.which("git")
    assert git is not None, "в образе нет git — конфликт слияния воспроизвести нечем"

    repo = _make_repo_with_conflict(tmp_path)
    fake_bin = _make_fake_bin(tmp_path)
    message = "merge(x): проверка (TRK-0)"

    conflicted = _run_script(repo, fake_bin, ["task/TRK-0", "-m", message])
    assert conflicted.returncode == 1, conflicted.stdout + conflicted.stderr
    assert "--continue" in conflicted.stdout

    _resolve_conflict(repo)

    continued = _run_script(repo, fake_bin, ["--continue"])
    assert continued.returncode == 0, continued.stdout + continued.stderr

    body = _commit_body(repo)
    assert body.splitlines()[0] == message
    assert "Merge-verified:" in body


def test_without_dash_m_the_conflict_path_keeps_the_old_behaviour(tmp_path: Path) -> None:
    """Без `-m` `--continue` работает как раньше: заголовок коммита — предложение git.

    Человек, начавший слияние не через скрипт, передаёт сообщение сам — правка это
    поведение не трогает.
    """
    git = shutil.which("git")
    assert git is not None, "в образе нет git — конфликт слияния воспроизвести нечем"

    repo = _make_repo_with_conflict(tmp_path)
    fake_bin = _make_fake_bin(tmp_path)

    conflicted = _run_script(repo, fake_bin, ["task/TRK-0"])
    assert conflicted.returncode == 1, conflicted.stdout + conflicted.stderr

    _resolve_conflict(repo)

    continued = _run_script(repo, fake_bin, ["--continue"])
    assert continued.returncode == 0, continued.stdout + continued.stderr

    body = _commit_body(repo)
    assert body.startswith("Merge branch 'task/TRK-0'")
    assert "Merge-verified:" in body


# --- Образ пересобирается из смёрженного дерева, до прогона (TRK-70) ----------------


def _make_repo_without_conflict(tmp_path: Path) -> Path:
    """Временный репозиторий с веткой `task/TRK-0`, которая не конфликтует с `main`:
    ветки трогают разные файлы. Сливается без остановки на конфликте — этим и
    проверяется обычный ход, не через `--continue`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, ["init", "--quiet"])
    _git(repo, ["checkout", "--quiet", "-b", "main"])
    _git(repo, ["config", "user.email", "test@example.invalid"])
    _git(repo, ["config", "user.name", "Test"])

    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    _git(repo, ["add", "main.txt"])
    _git(repo, ["commit", "--quiet", "-m", "база"])

    _git(repo, ["checkout", "--quiet", "-b", "task/TRK-0"])
    (repo / "branch.txt").write_text("ветка\n", encoding="utf-8")
    _git(repo, ["add", "branch.txt"])
    _git(repo, ["commit", "--quiet", "-m", "из ветки"])

    _git(repo, ["checkout", "--quiet", "main"])
    return repo


def test_the_image_is_rebuilt_before_the_suite_runs(tmp_path: Path) -> None:
    """TRK-70: пересборка (`compose build`) случается раньше прогона (`compose run`),
    и на каждый заход скрипта, не только на первый.

    Без этого ветка, меняющая `uv.lock` или `docker/Dockerfile.dev`, проверялась бы
    зависимостями, поставленными в образ до слияния, а `Merge-verified:` уходила бы в
    историю неправдой.
    """
    git = shutil.which("git")
    assert git is not None, "в образе нет git — слияние воспроизвести нечем"

    repo = _make_repo_without_conflict(tmp_path)
    log = tmp_path / "docker-invocations.log"
    fake_bin = _make_fake_bin_recording_invocations(tmp_path, log)

    done = _run_script(repo, fake_bin, ["task/TRK-0", "-m", "merge(x): проверка (TRK-0)"])
    assert done.returncode == 0, done.stdout + done.stderr

    invocations = log.read_text(encoding="utf-8").splitlines()
    assert invocations, "docker не вызван вовсе"
    build_at = next(i for i, line in enumerate(invocations) if line.startswith("compose build"))
    run_at = next(i for i, line in enumerate(invocations) if line.startswith("compose run"))
    assert build_at < run_at, f"пересборка не раньше прогона: {invocations!r}"


def test_a_failed_rebuild_stops_the_merge_like_a_red_suite(tmp_path: Path) -> None:
    """Неудачная пересборка отменяет слияние так же, как красный набор: `git merge
    --abort`, ветка осталась прежней, дерево не тронуто."""
    git = shutil.which("git")
    assert git is not None, "в образе нет git — слияние воспроизвести нечем"

    repo = _make_repo_without_conflict(tmp_path)
    bin_dir = tmp_path / "fakebin-broken"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = compose ] && [ "${2:-}" = build ]; then
    echo "поддельная пересборка красная" >&2
    exit 1
fi
echo "поддельный docker не знает команду: $*" >&2
exit 1
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    before = _git_output(repo, ["rev-parse", "HEAD"])

    done = _run_script(repo, bin_dir, ["task/TRK-0", "-m", "merge(x): проверка (TRK-0)"])
    assert done.returncode != 0, done.stdout + done.stderr

    after = _git_output(repo, ["rev-parse", "HEAD"])
    assert before == after, "ветка сдвинулась, хотя пересборка красная"
    assert _git_output(repo, ["status", "--porcelain"]) == "", "слияние осталось начатым"


# --- Линтер бэкенда и pnpm check интерфейса (TRK-117, решение владельца в TRK-110) ---


def test_a_red_lint_stops_the_merge_before_pytest_runs(tmp_path: Path) -> None:
    """Ветка с нарочной ошибкой `ruff` не сливается: `docker compose run --rm lint`
    гоняется безусловно и раньше набора, а его красный останавливает слияние так же,
    как красный `pytest` — `git merge --abort`, ветка осталась прежней."""
    git = shutil.which("git")
    assert git is not None, "в образе нет git — слияние воспроизвести нечем"

    repo = _make_repo_without_conflict(tmp_path)
    fake_bin = _make_fake_bin(tmp_path, lint_exit=1, label="fakebin-red-lint")

    before = _git_output(repo, ["rev-parse", "HEAD"])

    done = _run_script(repo, fake_bin, ["task/TRK-0", "-m", "merge(x): проверка (TRK-0)"])
    assert done.returncode != 0, done.stdout + done.stderr
    assert "lint" in (done.stdout + done.stderr)

    after = _git_output(repo, ["rev-parse", "HEAD"])
    assert before == after, "ветка сдвинулась, хотя lint красный"
    assert _git_output(repo, ["status", "--porcelain"]) == "", "слияние осталось начатым"


def _make_repo_with_ui(tmp_path: Path, *, branch_touches_ui: bool) -> Path:
    """Временный репозиторий с `ui/` уже в `main` и веткой `task/TRK-0`, которая либо
    трогает файл в `ui/`, либо трогает только файл вне его — управляет тем, гоняется ли
    `pnpm check` (дифф ветки против базы слияния, не смёрженного дерева, где `ui/` есть
    всегда)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, ["init", "--quiet"])
    _git(repo, ["checkout", "--quiet", "-b", "main"])
    _git(repo, ["config", "user.email", "test@example.invalid"])
    _git(repo, ["config", "user.name", "Test"])

    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    ui_dir = repo / "ui"
    ui_dir.mkdir()
    (ui_dir / "placeholder.txt").write_text("ui\n", encoding="utf-8")
    _git(repo, ["add", "main.txt", "ui/placeholder.txt"])
    _git(repo, ["commit", "--quiet", "-m", "база"])

    _git(repo, ["checkout", "--quiet", "-b", "task/TRK-0"])
    if branch_touches_ui:
        (ui_dir / "placeholder.txt").write_text("из ветки\n", encoding="utf-8")
        _git(repo, ["add", "ui/placeholder.txt"])
    else:
        (repo / "branch.txt").write_text("ветка\n", encoding="utf-8")
        _git(repo, ["add", "branch.txt"])
    _git(repo, ["commit", "--quiet", "-m", "из ветки"])

    _git(repo, ["checkout", "--quiet", "main"])
    return repo


def test_pnpm_check_is_skipped_when_the_branch_does_not_touch_ui(tmp_path: Path) -> None:
    """Ветка без изменений в `ui/` `pnpm check` не запускает: чистая ветка, трогающая
    только бэкенд, сливается, а поддельный `pnpm` не вызывается ни разу — если бы
    вызвался, лог был бы не пуст."""
    git = shutil.which("git")
    assert git is not None, "в образе нет git — слияние воспроизвести нечем"

    repo = _make_repo_with_ui(tmp_path, branch_touches_ui=False)
    fake_bin = _make_fake_bin(tmp_path, label="fakebin-no-ui")
    pnpm_log = tmp_path / "pnpm-invocations.log"
    _add_fake_pnpm(fake_bin, log=pnpm_log)

    done = _run_script(repo, fake_bin, ["task/TRK-0", "-m", "merge(x): проверка (TRK-0)"])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "не трогает ui/" in done.stdout

    assert not pnpm_log.exists(), f"pnpm вызван, хотя ветка ui/ не трогала: {pnpm_log.read_text()}"

    body = _commit_body(repo)
    assert "pnpm check — ветка не трогает ui/, не запускался" in body


def test_a_red_pnpm_check_stops_the_merge_when_the_branch_touches_ui(tmp_path: Path) -> None:
    """Ветка, трогающая `ui/`, с нарочной ошибкой (здесь — красным поддельным `pnpm
    check`, воспроизводящим красный `prettier`/eslint/vitest) не сливается: лог зовёт
    `pnpm` ровно один раз, слияние отменено, ветка осталась прежней."""
    git = shutil.which("git")
    assert git is not None, "в образе нет git — слияние воспроизвести нечем"

    repo = _make_repo_with_ui(tmp_path, branch_touches_ui=True)
    fake_bin = _make_fake_bin(tmp_path, label="fakebin-red-ui")
    pnpm_log = tmp_path / "pnpm-invocations.log"
    _add_fake_pnpm(fake_bin, exit_code=1, log=pnpm_log)

    before = _git_output(repo, ["rev-parse", "HEAD"])

    done = _run_script(repo, fake_bin, ["task/TRK-0", "-m", "merge(x): проверка (TRK-0)"])
    assert done.returncode != 0, done.stdout + done.stderr
    assert "ветка трогает ui/" in done.stdout

    assert pnpm_log.exists(), "pnpm ни разу не вызван, хотя ветка трогала ui/"
    invocation_count = pnpm_log.read_text(encoding="utf-8").count("\n")
    assert invocation_count == 1, f"pnpm check вызван не ровно один раз: {invocation_count}"

    after = _git_output(repo, ["rev-parse", "HEAD"])
    assert before == after, "ветка сдвинулась, хотя pnpm check красный"
    assert _git_output(repo, ["status", "--porcelain"]) == "", "слияние осталось начатым"


def test_the_merge_commit_records_lint_test_and_pnpm_check_outcomes(tmp_path: Path) -> None:
    """Чистая ветка, трогающая `ui/`, сливается как прежде — и строка `Merge-verified:`
    называет исход всех трёх прогонов: линтера, набора и `pnpm check`, а не только
    набора, как до TRK-117."""
    git = shutil.which("git")
    assert git is not None, "в образе нет git — слияние воспроизвести нечем"

    repo = _make_repo_with_ui(tmp_path, branch_touches_ui=True)
    fake_bin = _make_fake_bin(tmp_path, label="fakebin-green-ui")
    _add_fake_pnpm(fake_bin)

    done = _run_script(repo, fake_bin, ["task/TRK-0", "-m", "merge(x): проверка (TRK-0)"])
    assert done.returncode == 0, done.stdout + done.stderr

    body = _commit_body(repo)
    assert "Merge-verified:" in body
    assert "docker compose run --rm lint" in body
    assert "docker compose run --rm test" in body
    assert "pnpm check —" in body
    assert "не запускался" not in body
