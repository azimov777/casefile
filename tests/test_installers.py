"""Сторож проверки режима Windows-контейнеров в установщиках (TRK-67).

`install.sh` и `install.ps1` — близнецы: те же шаги в том же порядке (см. шапку
`install.ps1`). Проверка режима Docker Desktop добавлена в оба одинаково, сразу после
проверки «Docker запущен», и должна остановить установку до `docker compose pull`/`up`
понятной фразой про переключение на Linux-контейнеры. Ни то, ни другое не проверить
исполнением здесь: pwsh нет в этом образе (его гоняют в отдельном контейнере, заметка
`docs/notes/docker.md`), а настоящий Docker Desktop в режиме Windows-контейнеров есть
только на настоящем Windows. Сторожим текстом — как `tests/test_merge_script.py`
сторожит `scripts/merge-task-branch.sh`: дешёвая проверка, которая всё равно ловит
самое дорогое — исчезнувшую проверку или разъехавшуюся фразу.
"""

import re
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = PROJECT_ROOT / "install.sh"
INSTALL_PS1 = PROJECT_ROOT / "install.ps1"

#: Общая подстрока обеих фраз — по ней проверяется, что установщики не разошлись по
#: смыслу. Не вся фраза целиком: слова вокруг у sh и ps1 могут отличаться синтаксисом
#: кавычек, а этот кусок называет и причину, и действие.
SHARED_PHRASE = "Switch to Linux containers"

#: И то, и то читает режим тем же вызовом Docker, которым его сообщает сам Docker
#: (`docker info --format '{{.OSType}}'` — см. описание задачи TRK-67).
OS_TYPE_PROBE = "docker info --format '{{.OSType}}'"


def _read(path: Path) -> str:
    assert path.is_file(), f"нет файла {path}"
    return path.read_text(encoding="utf-8")


def test_both_installers_probe_the_same_docker_os_type() -> None:
    """Пропавшая проверка режима не остаётся незамеченной ни в одном из установщиков."""
    sh_text = _read(INSTALL_SH)
    ps1_text = _read(INSTALL_SH.parent / "install.ps1")

    assert OS_TYPE_PROBE in sh_text, f"install.sh не проверяет режим через {OS_TYPE_PROBE!r}"
    assert OS_TYPE_PROBE in ps1_text, f"install.ps1 не проверяет режим через {OS_TYPE_PROBE!r}"


def test_both_installers_branch_on_windows_mode() -> None:
    """Проверка режима действительно смотрит на значение `windows`, а не просто читает его."""
    sh_text = _read(INSTALL_SH)
    ps1_text = _read(INSTALL_PS1)
    windows = "windows"

    assert re.search(r"\bwindows\b", sh_text), f"install.sh не ищет значение {windows!r}"
    assert re.search(r"\bwindows\b", ps1_text), f"install.ps1 не ищет значение {windows!r}"


def test_both_installers_name_the_same_fix_in_the_error_message() -> None:
    """Фраза про переключение на Linux-контейнеры — общая по смыслу, а не только по коду."""
    sh_text = _read(INSTALL_SH)
    ps1_text = _read(INSTALL_PS1)

    assert SHARED_PHRASE in sh_text, f"install.sh: сообщение не называет {SHARED_PHRASE!r}"
    assert SHARED_PHRASE in ps1_text, f"install.ps1: сообщение не называет {SHARED_PHRASE!r}"


def test_the_windows_mode_check_comes_right_after_the_docker_is_running_check() -> None:
    """Проверка режима стоит до скачивания compose-файла и до `docker compose pull`/`up`.

    Дословно "сразу после" проверки «Docker запущен» здесь не по буквам, а по порядку
    относительно опасных операций: важно, что режим узнаётся раньше, чем установщик
    сходит за образами, а не что между строками нет ни одного символа.
    """
    sh_text = _read(INSTALL_SH)
    ps1_text = _read(INSTALL_PS1)

    for text, running_marker, pull_marker in (
        (sh_text, "Docker is not running", "docker compose pull"),
        (ps1_text, "Docker is not running", "compose pull"),
    ):
        running_at = text.index(running_marker)
        probe_at = text.index(OS_TYPE_PROBE)
        pull_at = text.index(pull_marker)
        assert running_at < probe_at < pull_at, (
            "проверка режима должна стоять между проверкой «Docker запущен» и "
            "скачиванием образов (docker compose pull)"
        )


def test_install_sh_still_parses() -> None:
    """Опечатка в install.sh обнаруживается здесь, а не на первом запуске установщика."""
    bash = shutil.which("bash")
    assert bash is not None, "в образе нет bash — проверить синтаксис нечем"
    done = subprocess.run([bash, "-n", str(INSTALL_SH)], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr
