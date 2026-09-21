"""`scripts/check-dco.sh` под тестом: единственное, что мешает первому чужому вкладу

незаметно отобрать у владельца право сменить лицензию ядра (TRK-89). Здесь же —
исключение для Dependabot (TRK-112), и оно самая опасная часть файла: узкое исключение,
сделанное неверно, превращается в дыру, которой воспользуется не бот, а любой человек,
вписавший его имя в свой коммит.

Проверки идут на временном git-репозитории с настоящим git — скрипту нужна история
коммитов, подделать которую текстом нельзя. `PR_AUTHOR_LOGIN`, которым в проде
`.github/workflows/dco.yml` передаёт скрипту `github.event.pull_request.user.login`,
здесь идёт переменной окружения теста — то же самое место входа, что и у конвейера.
"""

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "check-dco.sh"

#: Тот самый адрес, которым GitHub подписывает коммиты Dependabot во всех репозиториях —
#: числовой id учётной записи бота фиксирован, это не что-то, что задаёт репозиторий.
DEPENDABOT_EMAIL = "49699333+dependabot[bot]@users.noreply.github.com"


def _git(repo: Path, args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    """`main` с одним коммитом и веткой `task/x`, отведённой от него, — тестируемые

    коммиты идут в ветку, а не в `main` сам: диапазон `main..HEAD` иначе всегда пуст,
    ведь `HEAD` совпадал бы с `main`.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, ["init", "--quiet", "-b", "main"])
    _git(repo, ["config", "user.email", "test@example.invalid"])
    _git(repo, ["config", "user.name", "Test"])
    (repo / "base.txt").write_text("база\n", encoding="utf-8")
    _git(repo, ["add", "base.txt"])
    _git(repo, ["commit", "--quiet", "-m", "база"])
    _git(repo, ["checkout", "--quiet", "-b", "task/x"])
    return repo


def _commit(
    repo: Path,
    filename: str,
    message: str,
    *,
    author_name: str,
    author_email: str,
) -> None:
    (repo / filename).write_text(f"{filename}\n", encoding="utf-8")
    _git(repo, ["add", filename])
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = author_name
    env["GIT_AUTHOR_EMAIL"] = author_email
    subprocess.run(
        ["git", "commit", "--quiet", "-m", message],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_script(
    repo: Path, *, pr_author_login: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if pr_author_login is None:
        env.pop("PR_AUTHOR_LOGIN", None)
    else:
        env["PR_AUTHOR_LOGIN"] = pr_author_login
    return subprocess.run(
        [str(SCRIPT), "main..HEAD"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def test_the_script_is_there_and_carries_the_bit_to_run_it() -> None:
    """Бит запуска — часть содержимого файла, а не свойство машины (см. `test_merge_script.py`)."""
    assert SCRIPT.is_file(), f"нет файла {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} без бита запуска: в git он хранится как 100755"


def test_a_signed_off_commit_passes(tmp_path: Path) -> None:
    """Базовый зелёный путь: подпись совпадает с автором дословно."""
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        "feature.txt",
        "feat(x): добавить фичу\n\nSigned-off-by: Alice <alice@example.invalid>",
        author_name="Alice",
        author_email="alice@example.invalid",
    )

    done = _run_script(repo)

    assert done.returncode == 0, done.stdout + done.stderr


def test_a_commit_without_sign_off_fails(tmp_path: Path) -> None:
    """Базовый красный путь: обычный человеческий коммит без подписи не проходит."""
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        "feature.txt",
        "feat(x): добавить фичу",
        author_name="Alice",
        author_email="alice@example.invalid",
    )

    done = _run_script(repo)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "missing a Signed-off-by" in done.stderr


def test_a_dependabot_commit_is_exempt_when_github_says_the_pr_is_the_bots(tmp_path: Path) -> None:
    """Ровно сценарий TRK-112: коммит бота без подписи, PR открыт им же по данным GitHub.

    Dependabot не может подписаться — своего адреса, которым он отвечал бы за код, у него
    нет, — и настоящие его коммиты (проверено на PR #2 и #4) приходят без совпадающей
    `Signed-off-by` независимо от того, что бот пишет в теле сообщения.
    """
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        "uv.lock",
        "build(deps): bump astral-sh/uv from 0.12.13 to 0.12.16",
        author_name="dependabot[bot]",
        author_email=DEPENDABOT_EMAIL,
    )

    done = _run_script(repo, pr_author_login="dependabot[bot]")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "exempt as dependabot[bot]" in done.stdout


def test_impersonating_dependabot_in_the_commit_does_not_skip_the_check(tmp_path: Path) -> None:
    """Самозванец: коммит выглядит точь-в-точь как коммит бота (то же имя, тот же

    формат адреса), но открыл PR не бот — GitHub этого не подтверждает. Если бы проверка
    верила содержимому коммита, любой внешний вкладчик обошёл бы DCO этой одной строкой
    `git commit --author`; она обязана остаться красной.
    """
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        "payload.txt",
        "feat(x): совсем не то, чем кажется",
        author_name="dependabot[bot]",
        author_email=DEPENDABOT_EMAIL,
    )

    # PR_AUTHOR_LOGIN не выставлен вовсе — как при локальном запуске человеком.
    done = _run_script(repo, pr_author_login=None)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "missing a Signed-off-by" in done.stderr


def test_a_human_login_does_not_exempt_a_bot_looking_commit_either(tmp_path: Path) -> None:
    """То же самозванство, но с явным чужим `PR_AUTHOR_LOGIN` — на случай, если кто-то

    решит, что пустая переменная — единственное, от чего зависит защита.
    """
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        "payload.txt",
        "feat(x): совсем не то, чем кажется",
        author_name="dependabot[bot]",
        author_email=DEPENDABOT_EMAIL,
    )

    done = _run_script(repo, pr_author_login="mallory")

    assert done.returncode == 1, done.stdout + done.stderr


def test_a_human_commit_riding_along_a_dependabot_pr_still_needs_its_own_sign_off(
    tmp_path: Path,
) -> None:
    """Исключение узкое по коммиту, а не по PR целиком: даже когда GitHub числит PR за

    ботом, коммит с другим автором в том же диапазоне освобождения не получает.
    """
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        "uv.lock",
        "build(deps): bump astral-sh/uv from 0.12.13 to 0.12.16",
        author_name="dependabot[bot]",
        author_email=DEPENDABOT_EMAIL,
    )
    _commit(
        repo,
        "extra.txt",
        "fix(x): дополнительный коммит без подписи",
        author_name="Bob",
        author_email="bob@example.invalid",
    )

    done = _run_script(repo, pr_author_login="dependabot[bot]")

    assert done.returncode == 1, done.stdout + done.stderr
    assert "Bob" in done.stderr
