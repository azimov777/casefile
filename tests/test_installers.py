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

Тем же текстовым способом файл сторожит и то, что установщики спрашивают адрес MCP у
самой установки, а не собирают его из порта (TRK-71): см. `MCP_URL_PROBE` ниже.
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


#: Общий вызов, которым оба установщика спрашивают адрес MCP у самой установки — тем же
#: способом, каким интерфейс получает его через `GET /api/v1/installation`
#: (`Settings.effective_mcp_public_url`; см. описание задачи TRK-71). Сторожит пропавший
#: запрос к установке.
MCP_URL_PROBE = "get_settings().effective_mcp_public_url"


def test_both_installers_ask_the_installation_for_its_own_mcp_address() -> None:
    """Адрес MCP спрашивается у установки, а не у переменной окружения (TRK-71)."""
    sh_text = _read(INSTALL_SH)
    ps1_text = _read(INSTALL_PS1)

    assert MCP_URL_PROBE in sh_text, f"install.sh не спрашивает адрес через {MCP_URL_PROBE!r}"
    assert MCP_URL_PROBE in ps1_text, f"install.ps1 не спрашивает адрес через {MCP_URL_PROBE!r}"


def test_neither_installer_rebuilds_the_mcp_address_from_the_port() -> None:
    """Установщик не держит вторую копию правила адреса — он печатает ответ установки.

    Регресс к TRK-65#16: `mcp_port=$(setting TRACKER_MCP_PORT 8100)` (и её аналог в
    PowerShell) собирали `http://localhost:$mcp_port/mcp` сами, вместо того чтобы
    спросить установку, и расходились с ней при заданном `TRACKER_MCP_PUBLIC_URL`.
    """
    sh_text = _read(INSTALL_SH)
    ps1_text = _read(INSTALL_PS1)

    assert "mcp_port" not in sh_text, "install.sh снова собирает адрес из mcp_port"
    assert "mcpPort" not in ps1_text, "install.ps1 снова собирает адрес из mcpPort"
    assert "http://localhost:$mcp_port" not in sh_text
    assert "http://localhost:$mcpPort" not in ps1_text


def test_install_sh_still_parses() -> None:
    """Опечатка в install.sh обнаруживается здесь, а не на первом запуске установщика."""
    bash = shutil.which("bash")
    assert bash is not None, "в образе нет bash — проверить синтаксис нечем"
    done = subprocess.run([bash, "-n", str(INSTALL_SH)], capture_output=True, text=True)

    assert done.returncode == 0, done.stderr


# --- Установщик и обновлятор (TRK-131) -------------------------------------------------

#: Подставной `docker` для `install.sh`: пишет вызовы в `$CALLS`, отвечает по `$SCENE`.
FAKE_DOCKER = r"""#!/bin/sh
echo "$*" >>"$CALLS"
case "$*" in
  "info --format"*) echo linux ;;
  "create "*) echo holder ;;
  "cp "*) cp "$SCENE/compose" "$3" ;;
  "compose ps -q updater") cat "$SCENE/updater" 2>/dev/null ;;
  "exec "*" test -e /tmp/checking")
    n=$(cat "$SCENE/checking" 2>/dev/null || echo 0)
    [ "$n" -gt 0 ] || exit 1
    echo $((n - 1)) >"$SCENE/checking" ;;
  "top "*)
    n=$(cat "$SCENE/busy" 2>/dev/null || echo 0)
    echo "PID COMMAND"
    echo "1 sh"
    if [ "$n" -gt 0 ]; then echo $((n - 1)) >"$SCENE/busy"; echo "7 docker"; fi ;;
  "compose up "*) exit "$(cat "$SCENE/up" 2>/dev/null || echo 0)" ;;
  "compose run "*agent-token*) echo agent-token-secret ;;
  "compose run "*) echo http://localhost:8100/mcp ;;
esac
"""


def _install(tmp_path: Path, **scene: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """`install.sh` против подставного `docker`; `sleep` — мгновенный."""
    bin_dir, scene_dir = tmp_path / "bin", tmp_path / "scene"
    bin_dir.mkdir()
    scene_dir.mkdir()
    for name, body in {"docker": FAKE_DOCKER, "sleep": "#!/bin/sh\n"}.items():
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    (scene_dir / "compose").write_text("services: {}\n", encoding="utf-8")
    for name, body in scene.items():
        (scene_dir / name).write_text(body, encoding="utf-8")
    calls = tmp_path / "calls"
    calls.touch()
    done = subprocess.run(
        ["sh", str(INSTALL_SH)],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "CASEFILE_DIR": str(tmp_path / "casefile"),
            "CALLS": str(calls),
            "SCENE": str(scene_dir),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done, calls.read_text().splitlines()


def test_the_installer_waits_for_the_updater_check_and_holds_it_during_up(
    tmp_path: Path,
) -> None:
    """Идёт проверка обновлятора — дождаться её; дальше обновлятор стоит до `up`
    установщика, и два compose одновременно не работают."""
    done, calls = _install(tmp_path, updater="container-updater\n", busy="2")

    assert done.returncode == 0, done.stderr
    assert "Waiting for the updater to finish its check" in done.stdout
    assert "Casefile is running." in done.stdout
    stop = calls.index("stop container-updater")
    assert calls[stop - 1].startswith("top "), "остановлен только после своей проверки"
    assert len([c for c in calls if c.startswith("top ")]) == 3
    pull, up = calls.index("compose pull --quiet"), calls.index("compose up -d --remove-orphans")
    assert stop < pull < up
    assert "start container-updater" not in calls, "обновлятор поднимает `up` установщика"


def test_a_failed_install_starts_the_updater_again(tmp_path: Path) -> None:
    """Остановленный руками контейнер Docker сам не поднимет — это делает установщик."""
    done, calls = _install(tmp_path, updater="container-updater\n", up="1")

    assert done.returncode != 0
    assert calls[-1] == "start container-updater"


def test_a_first_install_has_no_updater_to_hold(tmp_path: Path) -> None:
    done, calls = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if c.startswith(("top ", "stop ", "start "))]


def test_install_ps1_holds_the_updater_the_same_way() -> None:
    """Близнец: та же остановка обновлятора до `pull` и тот же запуск при неудаче."""
    text = _read(INSTALL_PS1)

    assert text.index("$updater = Stop-Updater") < text.index("Invoke-Docker compose pull")
    assert "docker top $id -o 'pid,comm'" in text
    assert "& docker start $updater" in text.split("} finally {", 1)[1]


def test_the_installer_waits_while_the_updater_check_sleeps(tmp_path: Path) -> None:
    """Проверка ждёт здоровья служб (`sleep`), `docker` в ней не идёт — видно по файлу."""
    done, calls = _install(tmp_path, updater="container-updater\n", checking="2")

    assert done.returncode == 0, done.stderr
    assert "Waiting for the updater to finish its check" in done.stdout
    checks = [c for c in calls if c.startswith("exec ")]
    assert len(checks) == 3
    assert calls.index("stop container-updater") > calls.index(checks[-1])


def test_install_ps1_sees_the_check_by_its_file_too() -> None:
    assert "docker exec $id test -e /tmp/checking" in _read(INSTALL_PS1)
