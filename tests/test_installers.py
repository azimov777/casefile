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

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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
  "compose ps -aq db") cat "$SCENE/db" 2>/dev/null ;;
  "volume ls "*) cat "$SCENE/volume" 2>/dev/null ;;
  "compose exec -T db sh -c psql "*) cat "$SCENE/revision" 2>/dev/null ;;
  "compose config") cat "$SCENE/config" 2>/dev/null ;;
  "run --rm --pull never "*) cat "$SCENE/head" 2>/dev/null ;;
  "compose exec -T db sh -c pg_dump "*)
    [ "$(cat "$SCENE/dump" 2>/dev/null || echo ok)" = ok ] || exit 1
    echo dump-bytes ;;
  "compose run --rm --no-deps -T --entrypoint sh updater "*)
    cat >"$SCENE/snapshot"
    exit "$(cat "$SCENE/store" 2>/dev/null || echo 0)" ;;
  "compose up "*) exit "$(cat "$SCENE/up" 2>/dev/null || echo 0)" ;;
  "compose run "*agent-token*) echo agent-token-secret ;;
  "compose run "*) echo http://localhost:8100/mcp ;;
esac
"""


def _prepare(
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
    dotenv: str | None = None,
    **scene: str,
) -> tuple[dict[str, str], Path]:
    """Окружение для `install.sh`: подставные `docker` и `sleep`, сцена, `HOME` — `tmp_path`.

    Возвращает окружение и файл, в который заглушки пишут вызовы.
    """
    bin_dir, scene_dir = tmp_path / "bin", tmp_path / "scene"
    bin_dir.mkdir()
    scene_dir.mkdir(exist_ok=True)
    for name, body in {"docker": FAKE_DOCKER, "sleep": "#!/bin/sh\n"}.items():
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    (scene_dir / "compose").write_text("services: {}\n", encoding="utf-8")
    for name, body in scene.items():
        (scene_dir / name).write_text(body, encoding="utf-8")
    calls = tmp_path / "calls"
    calls.touch()
    install_dir = tmp_path / "casefile"
    if dotenv is not None:
        install_dir.mkdir(parents=True, exist_ok=True)
        (install_dir / ".env").write_text(dotenv, encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "CASEFILE_DIR": str(install_dir),
        "CALLS": str(calls),
        "SCENE": str(scene_dir),
        # Терминала нет: `/dev/tty` у процесса набора есть, когда его запустили из
        # терминала, и установщик (TRK-546) спросил бы согласие у человека за клавиатурой.
        # Тесты, которым терминал нужен, называют свой.
        "CASEFILE_TTY": str(tmp_path / "no-such-tty"),
    }
    env.update(extra_env or {})
    return env, calls


def _install(
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
    dotenv: str | None = None,
    **scene: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """`install.sh` против подставного `docker`; `sleep` — мгновенный.

    `dotenv`, если задан, кладётся в `.env` каталога установки *до* запуска — так, как
    он там лежит у существующей установки: сам установщик пишет в `.env` только
    `COMPOSE_FILE`, а названные ему реестр, выпуск, порты и проект
    (и то один раз). `extra_env` — переменные окружения самого вызова, поверх обязательных.
    """
    env, calls = _prepare(tmp_path, extra_env=extra_env, dotenv=dotenv, **scene)
    done = subprocess.run(
        ["sh", str(INSTALL_SH)],
        env=env,
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


# --- Порт доски в напечатанном адресе (TRK-169) -----------------------------------------


def test_the_installer_writes_named_ports_and_project_into_env_file(tmp_path: Path) -> None:
    """Названные установщику порты и проект compose остаются в `.env` (TRK-493): иначе
    обновлятор и `docker compose up` из каталога вернули бы 8080/8100 и проект `casefile`."""
    done, _ = _install(
        tmp_path,
        extra_env={
            "CASEFILE_PORT": "8180",
            "TRACKER_MCP_PORT": "8190",
            "COMPOSE_PROJECT_NAME": "trk-check",
        },
    )

    assert done.returncode == 0, done.stderr
    lines = (tmp_path / "casefile" / ".env").read_text(encoding="utf-8").splitlines()
    assert "CASEFILE_PORT=8180" in lines
    assert "TRACKER_MCP_PORT=8190" in lines
    assert "COMPOSE_PROJECT_NAME=trk-check" in lines


def test_the_installer_writes_no_ports_or_project_when_none_are_named(tmp_path: Path) -> None:
    """Установка на умолчаниях ведёт себя как прежде: в `.env` только `COMPOSE_FILE`."""
    done, _ = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    env_file = (tmp_path / "casefile" / ".env").read_text(encoding="utf-8")
    assert env_file.splitlines() == ["COMPOSE_FILE=docker-compose.prod.yml"]


def test_install_ps1_writes_ports_and_project_into_env_file() -> None:
    text = _read(INSTALL_PS1)

    for name in ("CASEFILE_PORT", "TRACKER_MCP_PORT", "COMPOSE_PROJECT_NAME"):
        assert f'$lines += "{name}=$env:{name}"' in text


def test_the_installer_prints_the_port_from_the_environment_variable(tmp_path: Path) -> None:
    """`CASEFILE_PORT` окружения красит вывод, даже если `.env` называет другой порт.

    Реальная публикация порта (`docker-compose.prod.yml`, `${CASEFILE_PORT:-8080}`) уже
    берёт окружение раньше `.env` — так работает подстановка переменных в самом compose.
    Напечатанный адрес обязан следовать тому же порядку, а не только `.env` (TRK-169).
    """
    done, _ = _install(
        tmp_path, extra_env={"CASEFILE_PORT": "18680"}, dotenv="CASEFILE_PORT=9091\n"
    )

    assert done.returncode == 0, done.stderr
    assert "Board:  http://localhost:18680" in done.stdout
    assert "9091" not in done.stdout


def test_the_installer_prints_the_port_from_env_file_without_the_variable(tmp_path: Path) -> None:
    """Без переменной окружения источник по-прежнему `.env` существующей установки."""
    done, _ = _install(tmp_path, dotenv="CASEFILE_PORT=9091\n")

    assert done.returncode == 0, done.stderr
    assert "Board:  http://localhost:9091" in done.stdout


def test_the_installer_prints_the_default_port_without_variable_or_env_file(tmp_path: Path) -> None:
    """Ни переменной, ни настройки в `.env` — печатается умолчание compose-файла, 8080."""
    done, _ = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    assert "Board:  http://localhost:8080" in done.stdout


def test_install_ps1_reads_the_port_the_same_order_as_install_sh() -> None:
    """Близнец: `$env:CASEFILE_PORT` проверяется раньше `Get-Setting`, как и в install.sh."""
    text = _read(INSTALL_PS1)

    expected = (
        "$uiPort = if ($env:CASEFILE_PORT) { $env:CASEFILE_PORT } "
        "else { Get-Setting 'CASEFILE_PORT' '8080' }"
    )
    assert expected in text


# --- Подключение и скил по харнессам (TRK-406) ------------------------------------------

AGENT_GUIDE = PROJECT_ROOT / "docs" / "agent-install.md"
SKILL_STEP = "Install the Casefile skill"

#: Команды скила дословно: их печатают оба установщика, и они же стоят в шаге гайда
#: (TRK-398#7). Разошлись хоть в одном флаге — агент по гайду и по выводу ставит разное.
SKILL_COMMANDS = (
    "claude plugin marketplace add azimov777/casefile#plugin",
    "claude plugin install casefile@casefile --scope user",
    "codex plugin marketplace add azimov777/casefile --ref plugin",
    "codex plugin add casefile@casefile",
    "hermes skills install azimov777/casefile/skills/casefile",
    "npx skills add azimov777/casefile#stable",
)

#: Строки подключения MCP у Hermes — вход OAuth без токена (TRK-495; до него ключом, TRK-452):
#: Claude Code и Codex подключает плагин, и токена для них установщик не печатает.
CONNECT_LINES = ("mcp_servers:", "auth: oauth", "opencode mcp auth casefile")


def test_both_installers_and_the_guide_carry_the_same_skill_commands() -> None:
    sh_text, ps1_text, guide = _read(INSTALL_SH), _read(INSTALL_PS1), _read(AGENT_GUIDE)

    for command in SKILL_COMMANDS:
        assert command in sh_text, f"install.sh не печатает {command!r}"
        assert command in ps1_text, f"install.ps1 не печатает {command!r}"
        assert command in guide, f"docs/agent-install.md не содержит {command!r}"
    for line in CONNECT_LINES:
        assert line in sh_text, f"install.sh не печатает {line!r}"
        assert line in ps1_text, f"install.ps1 не печатает {line!r}"
        assert line in guide, f"docs/agent-install.md не содержит {line!r}"
    for text in (sh_text, ps1_text, guide):
        assert "autoUpdate" in text and "extraKnownMarketplaces.casefile" in text


#: Проверка «стоит ли скил» по харнессам (TRK-431): те же признаки, по которым установщик
#: печатает `installed`, и строка только скила для установки, которую обновлятор уже
#: обновил, — ей скил не достаётся никогда. Строка — без адреса: плагин с адресом по
#: умолчанию несёт скил в Claude Code и Codex сразу (TRK-480), адрес нужен чужому серверу.
SKILL_CHECKS = (
    "claude plugin list",
    "codex plugin list",
    "hermes skills list",
    "~/.agents/skills/casefile/SKILL.md",
    "install.sh | CASEFILE_SKILL_ONLY=1 sh",
    "$env:CASEFILE_SKILL_ONLY=1; irm ",
)


def test_the_guide_checks_the_skill_before_installing_it() -> None:
    guide = _read(AGENT_GUIDE)
    step = guide[guide.index(f"## 4. {SKILL_STEP}") : guide.index("## 5. Verify")]
    check = step[step.index("### Check whether the skill is installed") :]

    for line in SKILL_CHECKS:
        assert line in check, f"шаг 4 гайда не проверяет скил строкой {line!r}"


def test_the_installers_print_the_harness_blocks_in_the_same_order() -> None:
    for text in (_read(INSTALL_SH), _read(INSTALL_PS1)):
        blocks = [
            re.search(pattern, text).start()  # type: ignore[union-attr]
            for pattern in (
                r"""["']Claude Code:["']""",
                r"""["']Codex:["']""",
                r"""["']Claude Desktop \(the chat app""",
                r"""["']Hermes \(OAuth""",
                r"""["']Any other MCP client""",
            )
        ]
        assert blocks == sorted(blocks)


def test_the_installer_prints_the_key_only_for_harnesses_without_oauth(
    tmp_path: Path,
) -> None:
    """Claude Code и Codex подключает плагин с входом OAuth: токена в их блоках нет.

    Ключ агента печатается только «прочим клиентам без OAuth», с путём, как прочитать его
    снова для сторожа журнала (TRK-452, TRK-469#25); ни в один файл он не пишется.
    """
    done, _ = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    out = done.stdout
    for command in SKILL_COMMANDS:
        assert command in out, f"вывод установщика не содержит {command!r}"
    blocks = {
        "claude": out[out.index("Claude Code:") : out.index("Codex:")],
        "codex": out[out.index("Codex:") : out.index("Hermes (OAuth")],
        "hermes": out[out.index("Hermes (OAuth") : out.index("Any other MCP client")],
        "other": out[out.index("Any other MCP client") : out.index("The skill teaches")],
    }
    for name in ("claude", "codex"):
        assert "agent-token-secret" not in blocks[name] and "Bearer" not in blocks[name], name
        assert "http://localhost:8100/mcp" in blocks[name], name
    assert "claude mcp login plugin:casefile:casefile" in blocks["claude"]
    assert "codex mcp login casefile" in blocks["codex"]
    assert 'url: "http://localhost:8100/mcp"' in blocks["hermes"]
    assert "auth: oauth" in blocks["hermes"] and "hermes mcp login casefile" in blocks["hermes"]
    assert "Bearer" not in blocks["hermes"] and "agent-token-secret" not in blocks["hermes"]
    assert "Authorization: Bearer agent-token-secret" in blocks["other"]
    assert "agent-token cat .secrets/agent-token" in blocks["other"]
    # Ключ печатается, но не пишется ни в один файл харнесса.
    assert not list(tmp_path.glob(".codex")) and not list(tmp_path.glob(".hermes"))


def _guide_step(title_start: str) -> str:
    text = _read(AGENT_GUIDE)
    start = text.index(title_start)
    nxt = re.search(r"^## ", text[start + 3 :], re.M)
    return text[start : start + 3 + nxt.start()] if nxt else text[start:]


def test_the_guide_has_the_skill_step_between_connect_and_verify() -> None:
    text = _read(AGENT_GUIDE)
    headings = re.findall(r"^## (\d+)\. (.+)$", text, re.M)
    titles = [title for _, title in headings]

    assert titles.index(SKILL_STEP) == titles.index("Connect yourself over MCP") + 1
    assert titles.index("Verify") == titles.index(SKILL_STEP) + 1
    assert [int(n) for n, _ in headings] == list(range(1, len(headings) + 1))


def test_the_guide_skill_step_reaches_the_shared_installation_and_verify() -> None:
    joining = _guide_step("### Joining an installation someone else runs")
    assert SKILL_STEP in joining, "подраздел «Joining…» не отсылает к шагу скила"

    verify = _guide_step("## 5. Verify")
    assert "claude plugin list" in verify and "codex plugin list" in verify


# --- Шаг «скил» установщиков (TRK-408) ---------------------------------------------------

#: Заглушки харнессов для `install.sh`: пишут вызовы в `$CALLS`; `claude` заводит
#: `settings.json`, как это делает настоящий `marketplace add`, и отвечает на `plugin list`.
#: Как настоящие (TRK-494), `add` отказывает, если маркетплейс уже объявлен с другим
#: источником: у `claude` — объявление `stable` в settings.json, у `codex` — `$SCENE/codex-stable`.
FAKE_CLAUDE = r"""#!/bin/sh
echo "claude $*" >>"$CALLS"
case "$*" in
  "plugin marketplace add"*)
    mkdir -p "$CLAUDE_CONFIG_DIR"
    if grep -q '"ref": *"stable"' "$CLAUDE_CONFIG_DIR/settings.json" 2>/dev/null; then
      # Слова отказа зависят от версии Claude Code (TRK-550): берутся из `$SCENE/claude-refusal`,
      # без него — слова до 2.1.289.
      if [ -f "$SCENE/claude-refusal" ]; then cat "$SCENE/claude-refusal" >&2
      else echo 'its network source differs from the one declared for it in settings' >&2; fi
      exit 1
    fi
    # Объявление уже на нужной ветке — настоящий `add` пишет «already on disk» и файл не
    # трогает (TRK-546: так видно, что байты settings.json меняет только установщик).
    if grep -q '"ref": *"plugin"' "$CLAUDE_CONFIG_DIR/settings.json" 2>/dev/null; then
      echo 'already on disk'
      exit 0
    fi
    python3 -c 'import json, os, sys
path = sys.argv[1]
o = json.load(open(path)) if os.path.exists(path) else {}
o.setdefault("extraKnownMarketplaces", {})["casefile"] = {
    "source": {"source": "git", "url": "u", "ref": "plugin"}}
json.dump(o, open(path, "w"), indent=2)' "$CLAUDE_CONFIG_DIR/settings.json" ;;
  "plugin install"*) [ -z "${FAIL_INSTALL:-}" ] || { echo "install refused" >&2; exit 1; } ;;
  "plugin configure casefile@casefile --json")
    [ -f "$SCENE/claude-url" ] || exit 1
    printf '{\n  "schema": {\n    "casefile_url": {\n      "type": "string"\n    }\n  },\n'
    printf '  "inputs": {\n    "casefile_url": "%s"\n  }\n}\n' "$(cat "$SCENE/claude-url")" ;;
  "mcp get "*) [ -f "$SCENE/claude-$3" ] && cat "$SCENE/claude-$3" || exit 1 ;;
  "mcp login "*) exit "$(cat "$SCENE/login-claude" 2>/dev/null || echo 0)" ;;
  "plugin list")
    printf 'Installed plugins:\n\n  > casefile@casefile\n    Version: 0.7.1\n'
    printf '    Scope: user\n    Status: enabled\n' ;;
esac
"""
FAKE_CODEX = r"""#!/bin/sh
echo "codex $*" >>"$CALLS"
case "$*" in
  "plugin marketplace add"*)
    if [ -f "$SCENE/codex-stable" ]; then
      echo "Error: marketplace 'casefile' is already added from a different source" >&2
      exit 1
    fi ;;
  "plugin marketplace remove casefile") rm -f "$SCENE/codex-stable" ;;
esac
[ "$*" != "plugin list" ] ||
  printf 'PLUGIN  STATUS  VERSION  PATH\ncasefile@casefile  installed, enabled  0.7.1  /x\n'
case "$*" in
  "mcp get "*) [ -f "$SCENE/codex-$3" ] && cat "$SCENE/codex-$3" || exit 1 ;;
  "mcp login "*) exit "$(cat "$SCENE/login-codex" 2>/dev/null || echo 0)" ;;
esac
"""
FAKE_NPX = r"""#!/bin/sh
echo "npx $*" >>"$CALLS"
mkdir -p "$HOME/.agents/skills/casefile" && touch "$HOME/.agents/skills/casefile/SKILL.md"
"""


def _with_harnesses(tmp_path: Path, **bodies: str) -> dict[str, str]:
    """Кладёт заглушки в `bin/` (его создаёт `_install`, поэтому заранее — свой каталог)."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in bodies.items():
        (stubs / name).write_text(body, encoding="utf-8")
        (stubs / name).chmod(0o755)
    python_dir = Path(shutil.which("python3") or "/usr/bin/python3").parent
    return {
        "PATH": f"{tmp_path / 'bin'}:{stubs}:/usr/bin:/bin:{python_dir}",
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
        "CASEFILE_SKILL_SOURCE": "example/casefile",
    }


def test_the_installers_carry_the_skill_step_and_its_variables() -> None:
    for text in (_read(INSTALL_SH), _read(INSTALL_PS1)):
        for name in ("CASEFILE_SKILL", "CASEFILE_SKILL_ONLY", "CASEFILE_SKILL_SOURCE"):
            assert name in text
        for command in (
            "plugin marketplace update casefile",
            "plugin update casefile@casefile",
            "plugin marketplace upgrade casefile",
            "--agent cursor",
        ):
            assert command in text, f"нет {command!r}"
        assert "CASEFILE_SKILL_ONLY=1" in text


def test_the_skill_only_mode_comes_before_any_docker_check() -> None:
    sh_text, ps1_text = _read(INSTALL_SH), _read(INSTALL_PS1)

    assert sh_text.index('"$SKILL_ONLY" = 1') < sh_text.index("command -v docker")
    assert ps1_text.index("if ($SkillOnly)") < ps1_text.index("Get-Command docker")


def test_skill_only_needs_no_docker_makes_no_directory_and_prints_no_token(
    tmp_path: Path,
) -> None:
    done, calls = _install(tmp_path, extra_env={"CASEFILE_SKILL_ONLY": "1"})

    assert done.returncode == 0, done.stderr
    assert calls == [], "режим только скила не должен звать docker"
    assert not (tmp_path / "casefile").exists()
    assert "agent-token-secret" not in done.stdout and "Bearer" not in done.stdout
    for line in ("Claude Code", "Codex", "Hermes", "Other agents"):
        assert re.search(rf"{line} +.*not found", done.stdout), f"нет строки not found: {line}"
    assert "Casefile is running" not in done.stdout


def test_skill_zero_skips_the_step_and_the_full_install_still_runs(tmp_path: Path) -> None:
    done, _ = _install(tmp_path, extra_env={"CASEFILE_SKILL": "0"})

    assert done.returncode == 0, done.stderr
    assert "Casefile is running." in done.stdout
    assert "Installing the Casefile skill" not in done.stdout


def test_the_full_install_runs_the_skill_step_after_the_contour_and_names_the_only_line(
    tmp_path: Path,
) -> None:
    done, _ = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert out.index("Casefile is running.") < out.index("Installing the Casefile skill")
    assert out.index("Installing the Casefile skill") < out.index("Claude Code:")
    assert "CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh" in out


SERVER = "https://casefile.example.com/mcp"
LOCAL_PLUGIN_INSTALL = (
    "claude plugin install casefile@casefile --scope user "
    "--config casefile_url=http://localhost:8100/mcp"
)


def test_the_skill_step_installs_updates_and_reports_each_harness_found(tmp_path: Path) -> None:
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX, npx=FAKE_NPX)
    done, calls = _install(
        tmp_path, extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": SERVER, **env}
    )

    assert done.returncode == 0, done.stderr
    claude = [c for c in calls if c.startswith("claude ") and "mcp get" not in c]
    assert claude == [
        "claude plugin configure casefile@casefile --json",
        "claude plugin marketplace add example/casefile#plugin",
        "claude plugin marketplace update casefile",
        f"claude plugin install casefile@casefile --scope user --config casefile_url={SERVER}",
        "claude plugin update casefile@casefile",
        "claude plugin list",
    ]
    assert "codex plugin marketplace add example/casefile --ref plugin" in calls
    assert not [c for c in calls if "marketplace remove" in c], "новой установке снимать нечего"
    assert "npx -y skills add example/casefile#stable -g -y --agent cursor" in calls
    assert re.search(r"Claude Code +installed 0\.7\.1 \(updates itself\)", done.stdout)
    assert re.search(r"Codex +installed 0\.7\.1", done.stdout)
    assert re.search(r"Hermes +not found", done.stdout)
    assert re.search(r"Other agents +installed", done.stdout)
    settings = (tmp_path / "claude" / "settings.json").read_text()
    assert '"autoUpdate": true' in settings


#: Как Claude Code отказывает в `marketplace add` с другим источником, чем объявленный в
#: settings.json: слова зависят от версии (TRK-550). Вторые — настоящий вывод 2.1.289.
CLAUDE_SOURCE_REFUSALS = {
    "before 2.1.289": "its network source differs from the one declared for it in settings\n",
    "since 2.1.289": (
        'Cannot add marketplace "casefile": its source doesn\'t match its extraKnownMarketplaces '
        "entry in user or managed settings; add it from the source that entry lists, or change "
        "the entry.\n"
    ),
}

#: Объявление маркетплейса у установки, поставленной до TRK-494: `stable` со `--sparse`, с
#: включённым плагином, его адресом и автообновлением.
OLD_CLAUDE_SETTINGS = {
    "enabledPlugins": {"casefile@casefile": True},
    "extraKnownMarketplaces": {
        "casefile": {
            "source": {
                "source": "git",
                "url": "u",
                "ref": "stable",
                "sparsePaths": [".claude-plugin", "skills"],
            },
            "autoUpdate": True,
        }
    },
    "pluginConfigs": {"casefile@casefile": {"options": {"casefile_url": SERVER}}},
}


@pytest.mark.parametrize("refusal", CLAUDE_SOURCE_REFUSALS.values(), ids=CLAUDE_SOURCE_REFUSALS)
def test_an_installation_from_stable_moves_to_the_plugin_branch_and_keeps_the_plugin(
    tmp_path: Path, refusal: str
) -> None:
    """Прежний источник `stable` снимается только после отказа `add` (TRK-494): у Claude
    Code — объявлением в settings.json, а не `marketplace remove`, который удалил бы и плагин
    с его настройками; у Codex — `marketplace remove`. Затем `add` повторяется на `plugin`.
    Отказ Claude Code называется по-разному в разных версиях, и снимается источник при обоих
    (TRK-550)."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    settings_path = tmp_path / "claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps(OLD_CLAUDE_SETTINGS), encoding="utf-8")
    done, calls = _install(
        tmp_path,
        extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": SERVER, **env},
        **{"codex-stable": "", "claude-refusal": refusal},
    )

    assert done.returncode == 0, done.stderr
    claude_add = "claude plugin marketplace add example/casefile#plugin"
    assert calls.count(claude_add) == 2, "add повторяется после снятия объявления"
    assert not [c for c in calls if c.startswith("claude plugin marketplace remove")]
    assert not [c for c in calls if c.startswith("claude plugin uninstall")]
    settings = json.loads(settings_path.read_text())
    entry = settings["extraKnownMarketplaces"]["casefile"]
    assert entry["source"]["ref"] == "plugin" and "sparsePaths" not in entry["source"]
    assert entry["autoUpdate"] is True, "автообновление ставится снова"
    assert settings["enabledPlugins"] == OLD_CLAUDE_SETTINGS["enabledPlugins"]
    assert settings["pluginConfigs"] == OLD_CLAUDE_SETTINGS["pluginConfigs"]

    codex_add = "codex plugin marketplace add example/casefile --ref plugin"
    assert calls.count(codex_add) == 2
    first, remove = calls.index(codex_add), calls.index("codex plugin marketplace remove casefile")
    assert first < remove < len(calls) - 1 - calls[::-1].index(codex_add)
    assert remove < calls.index("codex plugin add casefile@casefile")
    assert re.search(r"Claude Code +installed 0\.7\.1 \(updates itself\)", done.stdout)
    assert re.search(r"Codex +installed 0\.7\.1", done.stdout)
    # Вход Claude Code привязан к адресу, а не к источнику (TRK-502#6); на входе перевод не
    # замерен, поэтому установщик называет команду на случай «Needs authentication».
    assert re.search(
        r"Claude Code +moved to the plugin branch; the sign-in stays with the address - if "
        r'claude mcp list shows "Needs authentication": claude mcp login plugin:casefile:casefile',
        done.stdout,
    )


@pytest.mark.parametrize(
    "failure",
    [
        "network down",
        # Общее начало нового отказа ещё не отказ о несовпадении источника.
        'Cannot add marketplace "casefile": network down',
    ],
)
def test_another_add_failure_is_not_taken_for_an_old_source(tmp_path: Path, failure: str) -> None:
    """Источник снимается только при отказе «другой источник»: иная ошибка `add` — строка
    с командой повтора, settings.json не трогается."""
    add = '"plugin marketplace add"*)\n'
    failing = FAKE_CLAUDE.replace(add, add + f"    echo '{failure}' >&2; exit 1\n", 1)
    env = _with_harnesses(tmp_path, claude=failing)
    settings_path = tmp_path / "claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps(OLD_CLAUDE_SETTINGS), encoding="utf-8")
    done, calls = _install(
        tmp_path, extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": SERVER, **env}
    )

    assert done.returncode == 0, done.stderr
    assert calls.count("claude plugin marketplace add example/casefile#plugin") == 1
    assert json.loads(settings_path.read_text()) == OLD_CLAUDE_SETTINGS
    assert re.search(r"Claude Code +failed - repeat by hand:", done.stdout)


def test_skill_only_with_an_address_installs_the_plugin_without_docker_or_a_token(
    tmp_path: Path,
) -> None:
    """`CASEFILE_URL` — адрес сервера: плагин Claude Code получает его настройкой, а Codex —
    записью без токена в config.toml (у него адрес плагина зашит, TRK-451#13)."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, calls = _install(
        tmp_path, extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": SERVER, **env}
    )

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if c.startswith(("compose", "pull", "info", "create"))]
    assert not (tmp_path / "casefile").exists(), "каталог установки не создаётся"
    config = (tmp_path / ".codex" / "config.toml").read_text()
    assert config.strip() == f'[mcp_servers.casefile]\nurl = "{SERVER}"'
    assert f"connected to {SERVER}" in done.stdout
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name not in {"calls", "docker", "sleep"}:
            assert "trk_" not in path.read_text(errors="ignore"), path
    assert "Bearer" not in done.stdout


def test_skill_only_with_the_local_address_keeps_codex_on_the_plugin_address(
    tmp_path: Path,
) -> None:
    """Адрес плагина Codex — `127.0.0.1:8100`: тот же адрес (`localhost` — то же) записи не
    требует."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, calls = _install(
        tmp_path,
        extra_env={
            "CASEFILE_SKILL_ONLY": "1",
            "CASEFILE_URL": "http://localhost:8100/mcp",
            **env,
        },
    )

    assert done.returncode == 0, done.stderr
    assert not (tmp_path / ".codex" / "config.toml").exists()
    assert LOCAL_PLUGIN_INSTALL in calls


def test_skill_only_without_an_address_installs_the_plugin_with_the_default_one(
    tmp_path: Path,
) -> None:
    """Без `CASEFILE_URL` плагин Claude Code и Codex ставится с адресом по умолчанию (скил
    работает сразу, TRK-480): вход не ведётся, ручные записи не чистятся, config.toml Codex не
    пишется, печатается, как задать адрес сервера."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX, npx=FAKE_NPX)
    done, calls = _install(tmp_path, extra_env={"CASEFILE_SKILL_ONLY": "1", **env})

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if c.startswith(("compose", "pull", "info", "create"))]
    assert (
        "claude plugin install casefile@casefile --scope user "
        "--config casefile_url=http://127.0.0.1:8100/mcp"
    ) in calls
    assert "codex plugin add casefile@casefile" in calls
    touched = [c for c in calls if " login " in c or " mcp get " in c or " mcp remove " in c]
    assert not touched, touched
    assert not (tmp_path / ".codex" / "config.toml").exists()
    default = r"connected to http://127\.0\.0\.1:8100/mcp"
    assert re.search(rf"Claude Code +installed .*{default}", done.stdout)
    assert re.search(r"Codex +installed .*default address", done.stdout)
    assert "plugin not installed" not in done.stdout
    assert "no sign-in was started" in done.stdout
    assert "CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh" in done.stdout
    assert re.search(r"Other agents +installed", done.stdout)
    assert "Signing the agents in" not in done.stdout


def test_skill_only_without_an_address_keeps_the_address_the_plugin_already_has(
    tmp_path: Path,
) -> None:
    """Вход Claude Code лежит под ключом из имени сервера и адреса (TRK-502#6): установщик без
    `CASEFILE_URL` не подменяет рабочий `localhost` адресом по умолчанию `127.0.0.1`, иначе
    вход теряется (так было при переводе на ветку plugin, TRK-502#7)."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, calls = _install(
        tmp_path,
        extra_env={"CASEFILE_SKILL_ONLY": "1", **env},
        **{"claude-url": "http://localhost:8100/mcp"},
    )

    assert done.returncode == 0, done.stderr
    assert LOCAL_PLUGIN_INSTALL in calls
    assert not [c for c in calls if "casefile_url=http://127.0.0.1" in c]
    assert re.search(
        r"Claude Code +installed .*connected to http://localhost:8100/mcp \(kept the address",
        done.stdout,
    )
    assert "the address changed" not in done.stdout
    assert "Signing the agents in" not in done.stdout


def test_a_changed_address_tells_to_sign_claude_code_in_again(tmp_path: Path) -> None:
    """Названный адрес не совпадает с прежним хоть символом — у Claude Code это другой ключ
    входа: строка с прежним адресом и командой входа."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, calls = _install(
        tmp_path,
        extra_env={
            "CASEFILE_SKILL_ONLY": "1",
            "CASEFILE_URL": "http://127.0.0.1:8100/mcp",
            "CASEFILE_TTY": str(tmp_path / "no-such-tty"),
            **env,
        },
        **{"claude-url": "http://localhost:8100/mcp"},
    )

    assert done.returncode == 0, done.stderr
    assert (
        "claude plugin install casefile@casefile --scope user "
        "--config casefile_url=http://127.0.0.1:8100/mcp"
    ) in calls
    assert re.search(
        r"Claude Code +the address changed from http://localhost:8100/mcp: the sign-in belongs "
        r"to the address, sign in again: claude mcp login plugin:casefile:casefile",
        done.stdout,
    )


def test_the_same_address_says_nothing_about_signing_in_again(tmp_path: Path) -> None:
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, _ = _install(
        tmp_path,
        extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": SERVER, **env},
        **{"claude-url": SERVER},
    )

    assert done.returncode == 0, done.stderr
    assert "the address changed" not in done.stdout
    assert "moved to the plugin branch" not in done.stdout


def test_skill_only_refuses_an_http_address_outside_localhost(tmp_path: Path) -> None:
    """Вне петли служба отдаёт OAuth только по https (TRK-451#13): http — отказ до всего."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, calls = _install(
        tmp_path,
        extra_env={
            "CASEFILE_SKILL_ONLY": "1",
            "CASEFILE_URL": "http://203.0.113.7:8100/mcp",
            **env,
        },
    )

    assert done.returncode != 0
    assert "https" in done.stderr
    assert calls == []


# --- Ручные записи и вход OAuth (TRK-452) ------------------------------------------------

CLAUDE_GET = (
    "{name}:\n  Scope: User config (available in all your projects)\n  Type: http\n  URL: {url}\n"
)
CODEX_GET = '{{"name": "{name}", "transport": {{"type": "streamable_http", "url": "{url}"}}}}\n'


def test_the_manual_entries_of_this_installation_are_removed_and_the_others_stay(
    tmp_path: Path,
) -> None:
    """`casefile` с адресом этой установки уходит из обоих харнессов, `tracker` с чужим
    адресом остаётся; о каждом решении — строка (TRK-427#10)."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, calls = _install(
        tmp_path,
        extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": "http://localhost:8100/mcp", **env},
        **{
            "claude-casefile": CLAUDE_GET.format(name="casefile", url="http://127.0.0.1:8100/mcp"),
            "claude-tracker": CLAUDE_GET.format(
                name="tracker", url="https://other.example.com/mcp"
            ),
            "codex-casefile": CODEX_GET.format(name="casefile", url="http://localhost:8100/mcp"),
            "codex-tracker": CODEX_GET.format(name="tracker", url="https://other.example.com/mcp"),
        },
    )

    assert done.returncode == 0, done.stderr
    assert "claude mcp remove casefile --scope user" in calls
    assert "codex mcp remove casefile" in calls
    assert not [c for c in calls if "remove tracker" in c], "чужой адрес не трогается"
    assert re.search(r'Claude Code +removed the manual MCP entry "casefile"', done.stdout)
    assert re.search(r'Codex +removed the manual MCP entry "casefile"', done.stdout)
    assert re.search(r'Claude Code +left the MCP entry "tracker"', done.stdout)
    assert re.search(r'Codex +left the MCP entry "tracker"', done.stdout)
    assert calls.index("claude mcp remove casefile --scope user") < calls.index(
        LOCAL_PLUGIN_INSTALL
    )


def test_a_project_scope_entry_is_left_to_its_owner(tmp_path: Path) -> None:
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE)
    done, calls = _install(
        tmp_path,
        extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": SERVER, **env},
        **{
            "claude-casefile": CLAUDE_GET.replace("User config", "Project config").format(
                name="casefile", url=SERVER
            )
        },
    )

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if c.startswith("claude mcp remove")]
    assert re.search(r'Claude Code +left the manual MCP entry "casefile"', done.stdout)


def _skill_only_login(
    tmp_path: Path, scene: dict[str, str] | None = None, **extra: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    return _install(
        tmp_path,
        extra_env={"CASEFILE_SKILL_ONLY": "1", "CASEFILE_URL": SERVER, **env, **extra},
        **(scene or {}),
    )


def test_without_a_terminal_the_sign_in_is_not_started_and_the_commands_are_printed(
    tmp_path: Path,
) -> None:
    done, calls = _skill_only_login(tmp_path, CASEFILE_TTY=str(tmp_path / "no-such-tty"))

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if " mcp login" in c]
    assert "This needs a terminal" in done.stdout
    assert "claude mcp login plugin:casefile:casefile" in done.stdout
    assert "codex mcp login casefile" in done.stdout


def test_with_a_terminal_the_sign_in_runs_once_per_harness(tmp_path: Path) -> None:
    tty = tmp_path / "tty"
    tty.write_text("y\n")
    done, calls = _skill_only_login(tmp_path, CASEFILE_TTY=str(tty))

    assert done.returncode == 0, done.stderr
    assert "claude mcp login plugin:casefile:casefile" in calls
    assert "codex mcp login casefile" in calls
    assert re.search(r"Claude Code +signed in", done.stdout)
    assert re.search(r"Codex +signed in", done.stdout)
    assert "This needs a terminal" not in done.stdout


def test_a_failed_sign_in_is_a_line_with_the_command_and_does_not_fail_the_install(
    tmp_path: Path,
) -> None:
    tty = tmp_path / "tty"
    tty.write_text("y\n")
    done, _ = _skill_only_login(tmp_path, {"login-claude": "1"}, CASEFILE_TTY=str(tty))

    assert done.returncode == 0, done.stderr
    assert re.search(
        r"Claude Code +sign-in did not finish - repeat by hand: "
        r"claude mcp login plugin:casefile:casefile",
        done.stdout,
    )
    assert re.search(r"Codex +signed in", done.stdout), "ошибка одного входа не гасит второй"


def test_casefile_login_zero_prints_the_commands_even_with_a_terminal(tmp_path: Path) -> None:
    tty = tmp_path / "tty"
    tty.write_text("y\n")
    done, calls = _skill_only_login(tmp_path, CASEFILE_TTY=str(tty), CASEFILE_LOGIN="0")

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if " mcp login" in c]
    assert "claude mcp login plugin:casefile:casefile" in done.stdout


def test_the_full_install_connects_the_plugin_to_the_installation_address(tmp_path: Path) -> None:
    """Полная установка ставит плагин с адресом, который ей назвала сама установка."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX)
    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    assert LOCAL_PLUGIN_INSTALL in calls
    assert not (tmp_path / ".codex" / "config.toml").exists()
    assert "agent-token-secret" not in "".join(
        c for c in calls if c.startswith(("claude ", "codex "))
    )


def test_a_failed_skill_command_is_reported_with_a_retry_and_does_not_stop_the_install(
    tmp_path: Path,
) -> None:
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE)
    done, _ = _install(tmp_path, extra_env={"FAIL_INSTALL": "1", **env})

    assert done.returncode == 0, done.stderr
    assert "Casefile is running." in done.stdout
    assert re.search(r"Claude Code +failed - repeat by hand:", done.stdout)
    assert "claude plugin install casefile@casefile --scope user" in done.stdout
    assert "install refused" in done.stdout
    assert "Updates arrive by themselves" in done.stdout


# --- Близнец: те же шаги плагина и входа в install.ps1 (TRK-452) --------------------------

#: Дословные признаки шагов, которые обязаны быть в обоих установщиках.
PLUGIN_STEPS = (
    "--config casefile_url=",
    "--ref plugin",
    "differs from the one declared",
    "match its extraKnownMarketplaces entry",
    "plugin configure casefile@casefile --json",
    "kept the address it had",
    "the address changed from",
    "the sign-in belongs to the address, sign in again",
    "moved to the plugin branch; the sign-in stays with the address",
    "already added from a different source",
    "plugin marketplace remove casefile",
    "mcp login plugin:casefile:casefile",
    "mcp login casefile",
    "CASEFILE_URL",
    "CASEFILE_LOGIN",
    "CASEFILE_SKILL_ONLY",
    "no sign-in was started",
    "removed the manual MCP entry",
    "left the MCP entry",
    "This needs a terminal",
    "sign-in did not finish - repeat by hand",
    "must be an https:// address (http:// only for localhost)",
    "[mcp_servers.casefile]",
    "agent-token cat .secrets/agent-token",
    "Hermes (OAuth, no token)",
)


def test_both_installers_carry_the_plugin_and_sign_in_steps() -> None:
    for name, text in (("install.sh", _read(INSTALL_SH)), ("install.ps1", _read(INSTALL_PS1))):
        for step in PLUGIN_STEPS:
            assert step in text, f"{name} не содержит {step!r}"
        # Прежние ручные записи убираются под обоими именами и только в своих областях.
        assert "'casefile', 'tracker'" in text or "casefile tracker" in text, name


def test_both_installers_take_both_wordings_of_the_claude_code_source_refusal() -> None:
    """Фразы отказа — в одном сопоставлении, а не одна в строке, другая рядом в комментарии
    (TRK-550): прежняя установка со `stable` переводится на `plugin` при любой из них."""
    for name, text in (("install.sh", _read(INSTALL_SH)), ("install.ps1", _read(INSTALL_PS1))):
        lines = [
            line
            for line in text.splitlines()
            if not line.lstrip().startswith("#") and "differs from the one declared" in line
        ]
        assert len(lines) == 1, name
        assert "match its extraKnownMarketplaces entry" in lines[0], name


def test_install_ps1_prints_no_token_in_the_claude_code_and_codex_blocks() -> None:
    for text in (_read(INSTALL_SH), _read(INSTALL_PS1)):
        start = re.search(r"""["']Claude Code:["']""", text).start()  # type: ignore[union-attr]
        end = text.index("Hermes (OAuth, no token)")
        block = text[start:end]
        assert "Bearer" not in block and "$token" not in block
        assert "http_headers" not in text and "bearer_token_env_var" not in text


def test_both_installers_sign_in_only_with_a_terminal_and_after_the_plugin_step() -> None:
    sh_text, ps1_text = _read(INSTALL_SH), _read(INSTALL_PS1)

    assert '( : <"$TTY" ) 2>/dev/null' in sh_text
    assert "IsInputRedirected" in ps1_text and "IsOutputRedirected" in ps1_text
    assert sh_text.index("sign_in || true") < sh_text.index("sign_in() {")
    assert ps1_text.index("    Invoke-SignIn\n}") < ps1_text.index("function Invoke-SignIn")


def test_install_ps1_parses_when_powershell_is_available() -> None:
    """Парсер PowerShell без ошибок. В образе тестов pwsh нет (заметка `docs/notes/docker.md`):
    проверка идёт там, где он есть, например `docker run --platform linux/amd64
    mcr.microsoft.com/powershell`; здесь она пропускается."""
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh отсутствует")
    script = (
        "$e=$null;$t=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL_PS1}',[ref]$t,[ref]$e);"
        "if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }"
    )
    done = subprocess.run([pwsh, "-NoProfile", "-Command", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


# --- Согласие, копии и точечная запись (TRK-546) ----------------------------------------
#
# Установщик не меняет файлы чужих программ без согласия человека (Beads потерял доверие
# тем, что переписывал `~/.claude/settings.json` без вопроса, TRK-527#7): перед шагом скила
# печатает, что изменит, и на терминале спрашивает «y/N»; «N» пропускает шаг целиком.
# Перед первой правкой файла рядом остаётся его копия `.casefile-bak`, а `settings.json`
# получает одну текстовую вставку, а не перезапись.

BOM = "\ufeff"
SETTINGS_4 = json.dumps(
    {
        "model": "opus",
        "env": {"NOTE": "тест é", "HTML": "<a href='x'>&</a>", "N": 1.0},
        "extraKnownMarketplaces": {
            "casefile": {"source": {"source": "git", "url": "u", "ref": "plugin"}},
            "other": {"source": {"source": "github", "repo": "a/b"}},
        },
        "enabledPlugins": {"casefile@casefile": True},
    },
    indent=4,
    ensure_ascii=False,
)
CODEX_TOML = (
    '# hand-written\nmodel = "gpt"\n\n[mcp_servers.other]\nurl = "https://o.example.com/mcp"'
)


def _terminal(tmp_path: Path, answer: str) -> dict[str, str]:
    """Свой «терминал» теста: файл с ответом человека; `CASEFILE_TTY` называет его."""
    tty = tmp_path / "tty"
    tty.write_text(answer, encoding="utf-8")
    return {"CASEFILE_TTY": str(tty)}


def _harness_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    return {
        **_with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX, npx=FAKE_NPX),
        "CASEFILE_SKILL_ONLY": "1",
        "CASEFILE_URL": SERVER,
        **extra,
    }


def _other_programs_files(tmp_path: Path) -> dict[Path, str]:
    """Чужие файлы такими, какими они лежали у человека: настройки, конфиг, записи MCP."""
    files = {
        tmp_path / "claude" / "settings.json": SETTINGS_4,
        tmp_path / "claude" / ".claude.json": '{"mcpServers": {"casefile": {"url": "x"}}}\n',
        tmp_path / ".codex" / "config.toml": CODEX_TOML,
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return files


def _manual_entries(url: str) -> dict[str, str]:
    """Прежние ручные записи MCP `casefile` у обоих харнессов, с адресом `url`."""
    return {
        "claude-casefile": CLAUDE_GET.format(name="casefile", url=url),
        "codex-casefile": CODEX_GET.format(name="casefile", url=url),
    }


def test_answering_n_touches_no_file_of_another_program(tmp_path: Path) -> None:
    """«N» пропускает шаг плагина целиком: ни одной команды харнесса, ни байта в их файлах,
    ни копии рядом. Сервер ставится как обычно, а вывод говорит, как поставить плагин позже."""
    files = _other_programs_files(tmp_path)
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX, npx=FAKE_NPX)
    done, calls = _install(
        tmp_path,
        extra_env={**env, **_terminal(tmp_path, "n\n")},
        **_manual_entries("http://localhost:8100/mcp"),
    )

    assert done.returncode == 0, done.stderr
    for path, text in files.items():
        assert path.read_bytes() == text.encode("utf-8"), path
    assert not list(tmp_path.rglob("*.casefile-bak"))
    assert not [c for c in calls if c.startswith(("claude ", "codex ", "npx ", "hermes "))], calls
    assert not (tmp_path / ".agents").exists()
    assert "compose up -d --remove-orphans" in calls and "Casefile is running." in done.stdout
    out = done.stdout
    assert "Install the plugin and make these changes? [y/N]" in out
    assert "Skipped: no file of another program was touched" in out
    assert "| CASEFILE_SKILL=1 sh" in out, "строка, как поставить плагин позже"
    assert "Signing the agents in" not in out and "signed in" not in out
    assert "The plugin is not installed: you skipped that step" in out
    assert "claude plugin marketplace add azimov777/casefile#plugin" in out


@pytest.mark.parametrize("answer", ["", "no\n", "\n", "yep\n"])
def test_anything_but_yes_is_no(tmp_path: Path, answer: str) -> None:
    """Пустой ответ и конец ввода — «N»: согласие должно быть сказано, а не угадано."""
    done, calls = _install(
        tmp_path,
        extra_env={**_harness_env(tmp_path), **_terminal(tmp_path, answer)},
    )

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if c.startswith(("claude ", "codex ", "npx "))]
    assert "Skipped: no file of another program was touched" in done.stdout


def test_skill_only_n_says_how_to_install_later_with_its_own_address(tmp_path: Path) -> None:
    done, _ = _install(tmp_path, extra_env={**_harness_env(tmp_path), **_terminal(tmp_path, "n\n")})

    assert done.returncode == 0, done.stderr
    assert (f"| CASEFILE_SKILL=1 CASEFILE_SKILL_ONLY=1 CASEFILE_URL={SERVER} sh") in done.stdout
    assert "no sign-in was started" not in done.stdout


def test_answering_y_saves_copies_and_changes_only_the_named_lines(tmp_path: Path) -> None:
    """«y»: рядом с каждым тронутым файлом лежит копия с исходными байтами; в settings.json
    прибавилась одна вставка `autoUpdate` (остальное — байт в байт, включая отступы и
    не-ASCII), в config.toml — дописаны строки адреса, запись MCP убрана командой харнесса."""
    files = _other_programs_files(tmp_path)
    done, calls = _install(
        tmp_path,
        extra_env={**_harness_env(tmp_path), **_terminal(tmp_path, "y\n")},
        **_manual_entries(SERVER),
    )

    assert done.returncode == 0, done.stderr
    for path, text in files.items():
        bak = path.with_name(path.name + ".casefile-bak")
        assert bak.read_bytes() == text.encode("utf-8"), f"копия {bak.name} — не исходник"
    assert "claude mcp remove casefile --scope user" in calls
    assert "codex mcp remove casefile" in calls

    settings = (tmp_path / "claude" / "settings.json").read_text(encoding="utf-8")
    removed, inserted = _single_edit(SETTINGS_4, settings)
    assert removed == "" and re.sub(r"\s", "", inserted) == ',"autoUpdate":true', (
        removed,
        inserted,
    )
    before, after = json.loads(SETTINGS_4), json.loads(settings)
    assert after["extraKnownMarketplaces"]["casefile"].pop("autoUpdate") is True
    assert after == before

    config = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert config == f'{CODEX_TOML}\n[mcp_servers.casefile]\nurl = "{SERVER}"\n'
    for line in (
        "Install the plugin and make these changes? [y/N]",
        "settings.json: the claude command adds the plugin there",
        '"autoUpdate": true goes into extraKnownMarketplaces.casefile',
        "config.toml: the codex command adds the plugin there",
        "are removed",
        "Other agents",
    ):
        assert line in done.stdout, line
    assert re.search(
        r"Claude Code +saved a copy of .*settings\.json as settings\.json\.casefile-bak",
        done.stdout,
    )
    assert re.search(r"Claude Code +installed 0\.7\.1 \(updates itself\)", done.stdout)
    assert (tmp_path / ".agents" / "skills" / "casefile" / "SKILL.md").exists()


def test_the_list_names_only_what_the_step_will_touch(tmp_path: Path) -> None:
    """Без `CASEFILE_URL` адрес сервера неизвестен: чужие записи MCP не удаляются, а значит
    и в списке их нет. Не найденный харнесс в списке не значится."""
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE)
    done, _ = _install(
        tmp_path,
        extra_env={**env, "CASEFILE_SKILL_ONLY": "1", **_terminal(tmp_path, "n\n")},
    )

    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert "settings.json: the claude command adds the plugin there" in out
    assert "are removed" not in out, "адрес неизвестен: записи MCP не трогаются"
    assert "config.toml" not in out and "npx skills add)" not in out


def test_without_a_terminal_nothing_is_asked_and_the_step_goes_by_casefile_skill(
    tmp_path: Path,
) -> None:
    """Агент и CI (stdin не терминал, `/dev/tty` нет) не ждут ответа: шаг идёт, как шёл, а
    список изменений остаётся в журнале."""
    done, calls = _install(tmp_path, extra_env=_harness_env(tmp_path))

    assert done.returncode == 0, done.stderr
    assert "[y/N]" not in done.stdout
    assert "No terminal to ask on, so it goes ahead" in done.stdout
    assert (
        f"claude plugin install casefile@casefile --scope user --config casefile_url={SERVER}"
        in calls
    )
    assert re.search(r"Claude Code +installed 0\.7\.1", done.stdout)


def test_casefile_skill_one_is_the_answer_given_in_advance(tmp_path: Path) -> None:
    """Названная явно `CASEFILE_SKILL=1` — «да» заранее: вопроса нет и на терминале; а при
    `CASEFILE_SKILL=0` нет и самого шага."""
    done, calls = _install(
        tmp_path,
        extra_env={**_harness_env(tmp_path), **_terminal(tmp_path, "n\n"), "CASEFILE_SKILL": "1"},
    )

    assert done.returncode == 0, done.stderr
    assert "[y/N]" not in done.stdout
    assert "CASEFILE_SKILL=1 is set: going ahead without asking" in done.stdout
    assert any(c.startswith("claude plugin install") for c in calls)


def test_casefile_skill_zero_asks_nothing_and_touches_nothing(tmp_path: Path) -> None:
    files = _other_programs_files(tmp_path)
    env = _with_harnesses(tmp_path, claude=FAKE_CLAUDE, codex=FAKE_CODEX, npx=FAKE_NPX)
    done, calls = _install(
        tmp_path,
        extra_env={**env, **_terminal(tmp_path, "y\n"), "CASEFILE_SKILL": "0"},
    )

    assert done.returncode == 0, done.stderr
    assert "[y/N]" not in done.stdout and "Installing the Casefile skill" not in done.stdout
    assert not [c for c in calls if c.startswith(("claude ", "codex ", "npx "))]
    assert not list(tmp_path.rglob("*.casefile-bak"))
    for path, text in files.items():
        assert path.read_bytes() == text.encode("utf-8"), path


def test_plugin_autoupdate_zero_installs_the_plugin_and_writes_no_autoupdate(
    tmp_path: Path,
) -> None:
    """`CASEFILE_PLUGIN_AUTOUPDATE=0`: плагин ставится, а `autoUpdate` в settings.json не
    пишется; в выводе — строка об этом и команда ручного обновления. Копия по-прежнему есть:
    сама команда `claude` тоже правит этот файл."""
    _other_programs_files(tmp_path)
    done, calls = _install(
        tmp_path,
        extra_env={
            **_harness_env(tmp_path),
            **_terminal(tmp_path, "y\n"),
            "CASEFILE_PLUGIN_AUTOUPDATE": "0",
        },
    )

    assert done.returncode == 0, done.stderr
    settings = tmp_path / "claude" / "settings.json"
    assert "autoUpdate" not in settings.read_text(encoding="utf-8")
    assert settings.read_bytes() == SETTINGS_4.encode("utf-8")
    assert settings.with_name("settings.json.casefile-bak").exists()
    assert any(c.startswith("claude plugin install") for c in calls)
    assert re.search(
        r"Claude Code +installed 0\.7\.1, connected to .* \(automatic updates not switched on, "
        r"as CASEFILE_PLUGIN_AUTOUPDATE=0 says; to update by hand: "
        r"claude plugin update casefile@casefile\)",
        done.stdout,
    )
    assert "goes into extraKnownMarketplaces.casefile" not in done.stdout, "список честен"


def test_a_second_run_does_not_overwrite_the_copy(tmp_path: Path) -> None:
    """Копия — исходник человека, а не вчерашнее состояние: повторный запуск её не затирает,
    даже если файл с тех пор изменился."""
    bak = tmp_path / "claude" / "settings.json.casefile-bak"
    _other_programs_files(tmp_path)
    bak.write_text("the very first original", encoding="utf-8")
    done, _ = _install(tmp_path, extra_env={**_harness_env(tmp_path), **_terminal(tmp_path, "y\n")})

    assert done.returncode == 0, done.stderr
    assert bak.read_text(encoding="utf-8") == "the very first original"
    assert not re.search(r"saved a copy of \S*settings\.json ", done.stdout)


def test_a_failed_copy_leaves_the_file_and_the_harness_alone(tmp_path: Path) -> None:
    """Копию сделать не вышло — файл не меняется и команды харнесса не идут: правка без
    копии — ровно то, ради чего шаг устроен."""
    files = _other_programs_files(tmp_path)
    env = _harness_env(tmp_path)
    stubs = Path(env["PATH"].split(":")[1])
    (stubs / "cp").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (stubs / "cp").chmod(0o755)
    done, calls = _install(tmp_path, extra_env={**env, **_terminal(tmp_path, "y\n")})

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if c.startswith(("claude ", "codex "))], calls
    for path, text in files.items():
        assert path.read_bytes() == text.encode("utf-8"), path
    assert "could not save a copy of" in done.stdout


# Терминал, как он у человека, а не файл: `curl | sh` — stdin там труба, ответ идёт с
# управляющего терминала. Драйвер даёт ребёнку свой pty как управляющий терминал и вывод
# либо на него (человек), либо в трубы (агент, унаследовавший терминал сеанса).
PTY_DRIVER = r"""
import fcntl, json, os, pty, select, subprocess, sys, termios, time

answer, on_terminal, command = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
master, slave = pty.openpty()


def own_terminal():
    os.setsid()
    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)


stdio = slave if on_terminal else subprocess.PIPE
proc = subprocess.Popen(
    ["sh", "-c", command], stdin=subprocess.DEVNULL, stdout=stdio, stderr=stdio,
    preexec_fn=own_terminal,
)
timed_out, out = False, b""
if on_terminal:
    os.close(slave)
    answered, deadline = False, time.time() + 40
    while time.time() < deadline:
        if select.select([master], [], [], 0.2)[0]:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if not answered and b"[y/N]" in out:
                os.write(master, answer.encode() + b"\n")
                answered = True
        elif proc.poll() is not None:
            break
    timed_out = proc.poll() is None
    if timed_out:
        proc.kill()
    proc.wait()
else:
    try:
        stdout, stderr = proc.communicate(timeout=40)
        out = stdout + stderr
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.communicate()
text = out.decode(errors="replace")
print(json.dumps({"rc": proc.returncode, "out": text, "timed_out": timed_out}))
"""


def _curl_pipe_sh(
    tmp_path: Path, answer: str, *, on_terminal: bool, **extra: str
) -> tuple[dict[str, object], list[str]]:
    """`cat install.sh | sh` — как `curl … | sh` — с управляющим терминалом `/dev/tty`."""
    pytest.importorskip("pty")
    env, calls = _prepare(
        tmp_path, extra_env={**_harness_env(tmp_path), "CASEFILE_TTY": "", **extra}
    )
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            PTY_DRIVER,
            answer,
            "1" if on_terminal else "0",
            f"cat {INSTALL_SH} | sh",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout), calls.read_text().splitlines()


def test_curl_pipe_sh_in_a_terminal_asks_on_the_controlling_terminal_and_n_skips(
    tmp_path: Path,
) -> None:
    """Главный путь человека: stdin — труба со скриптом, вопрос идёт через `/dev/tty`."""
    files = _other_programs_files(tmp_path)
    result, calls = _curl_pipe_sh(tmp_path, "n", on_terminal=True)

    assert not result["timed_out"], result["out"]
    assert "Install the plugin and make these changes? [y/N]" in str(result["out"])
    assert "Skipped: no file of another program was touched" in str(result["out"])
    assert not [c for c in calls if c.startswith(("claude ", "codex ", "npx "))], calls
    for path, text in files.items():
        assert path.read_bytes() == text.encode("utf-8"), path


def test_curl_pipe_sh_in_a_terminal_y_installs_the_plugin(tmp_path: Path) -> None:
    result, calls = _curl_pipe_sh(tmp_path, "y", on_terminal=True)

    assert not result["timed_out"], result["out"]
    assert any(c.startswith("claude plugin install") for c in calls), result["out"]
    assert "Skipped" not in str(result["out"])


def test_an_agent_that_inherited_the_terminal_is_not_asked_and_does_not_hang(
    tmp_path: Path,
) -> None:
    """`/dev/tty` открывается и у процесса, запущенного агентом из терминала, но вывод у него
    в трубах, и ответа не даст никто: вопроса нет, шаг идёт по `CASEFILE_SKILL`."""
    result, calls = _curl_pipe_sh(tmp_path, "n", on_terminal=False)

    assert not result["timed_out"], result["out"]
    assert "[y/N]" not in str(result["out"])
    assert "No terminal to ask on, so it goes ahead" in str(result["out"])
    assert any(c.startswith("claude plugin install") for c in calls)


# Точечная запись settings.json: одна текстовая вставка, а не пересборка файла. Тот же
# алгоритм у node и python3 (jq файл пересобирает целиком и не годится); `install.ps1` — тот
# же сканер на PowerShell, там проверка текстом ниже.


def _settings_vectors() -> dict[str, str]:
    base = {
        "model": "opus",
        "extraKnownMarketplaces": {
            "casefile": {"source": {"source": "git", "url": "https://x/y.git", "ref": "plugin"}}
        },
        "x": [1, 2, {"a": "}"}],
    }
    two = {
        "extraKnownMarketplaces": {
            "first": {"source": {"source": "github"}},
            "casefile": {"source": {"source": "git"}, "autoUpdate": False},
            "last": {"s": 1},
        },
        "tail": '\\"}{',
    }
    on = {"extraKnownMarketplaces": {"casefile": {"source": {"source": "git"}, "autoUpdate": True}}}
    last = {"extraKnownMarketplaces": {"a": {"s": 1}, "casefile": {"source": {"source": "git"}}}}
    plain = json.dumps(base, indent=2) + "\n"
    return {
        "indent2": plain,
        "indent4_no_final_newline": json.dumps(base, indent=4),
        "tabs": json.dumps(base, indent="\t") + "\n",
        "compact": json.dumps(base, separators=(",", ":")),
        "crlf": plain.replace("\n", "\r\n"),
        "bom": BOM + plain,
        "autoupdate_false": json.dumps(two, indent=2) + "\n",
        "autoupdate_true": json.dumps(on, indent=2) + "\n",
        "casefile_last": json.dumps(last, indent=2) + "\n",
        "no_marketplaces": json.dumps({"model": "x"}, indent=2) + "\n",
        "no_casefile": json.dumps({"extraKnownMarketplaces": {"a": {"s": 1}}}, indent=2) + "\n",
        "unicode": json.dumps(
            {"t": "тест é 💥", "extraKnownMarketplaces": {"casefile": {"source": {"k": "v"}}}},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        "spaced_colon": (
            '{\n  "extraKnownMarketplaces" : {\n    "casefile" : {\n'
            '      "source" : {"k": 1}\n    }\n  }\n}\n'
        ),
        "numbers": (
            '{"n": 1.0, "big": 12345678901234567890, "e": 1E3, '
            '"extraKnownMarketplaces": {"casefile": {"source": {}}}}'
        ),
    }


SETTINGS_VECTORS = _settings_vectors()
#: Объявления `casefile` нет: `auto_update` отказывает, `drop` ничего не делает.
NO_CASEFILE = {"no_marketplaces", "no_casefile"}
SETTINGS_TOOLS = [
    "python3",
    pytest.param(
        "node", marks=pytest.mark.skipif(shutil.which("node") is None, reason="node отсутствует")
    ),
]


def _single_edit(old: str, new: str) -> tuple[str, str]:
    """`new` — это `old` с одним заменённым куском: (что убрано, что вставлено)."""
    limit = min(len(old), len(new))
    head = 0
    while head < limit and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < limit - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    return old[head : len(old) - tail], new[head : len(new) - tail]


def _shell_functions(*names: str) -> str:
    """Определения функций `install.sh` по именам: в строку или до `}` в первом столбце."""
    text = _read(INSTALL_SH)
    found = []
    for name in names:
        match = re.search(rf"^{name}\(\) \{{.*\}}$", text, re.M) or re.search(
            rf"^{name}\(\) \{{[^\n]*\n.*?^\}}$", text, re.M | re.S
        )
        assert match, f"в install.sh нет функции {name}"
        found.append(match.group(0))
    return "\n".join(found)


def _edit_settings(tmp_path: Path, tool: str, op: str, text: str) -> tuple[int, str]:
    """`claude_settings <op>` из `install.sh` над файлом с этим текстом, при PATH только с
    нужным инструментом: так видно, какой из двух (node, python3) отработал."""
    work = tmp_path / f"{tool}-{op}"
    (work / "claude").mkdir(parents=True)
    (work / "bin").mkdir()
    settings = work / "claude" / "settings.json"
    settings.write_bytes(text.encode("utf-8"))
    for name in (tool, "cmp", "cat", "mktemp", "rm"):
        found = shutil.which(name)
        assert found, name
        (work / "bin" / name).symlink_to(found)
    script = (
        "set -eu\n"
        + _shell_functions("claude_settings_file", "claude_settings")
        + f"\nskill_tmp=$(mktemp -d)\nclaude_settings {op}\n"
    )
    done = subprocess.run(
        ["/bin/sh", "-c", script],
        env={
            "PATH": str(work / "bin"),
            "HOME": str(work),
            "CLAUDE_CONFIG_DIR": str(work / "claude"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done.returncode, settings.read_bytes().decode("utf-8")


@pytest.mark.parametrize("tool", SETTINGS_TOOLS)
@pytest.mark.parametrize("name", SETTINGS_VECTORS)
def test_auto_update_is_one_insertion_and_everything_else_stays_byte_for_byte(
    tmp_path: Path, tool: str, name: str
) -> None:
    old = SETTINGS_VECTORS[name]
    code, new = _edit_settings(tmp_path, tool, "auto_update", old)

    if name in NO_CASEFILE:
        assert code == 1 and new == old, "нет объявления — отказ, файл не тронут"
        return
    assert code == 0
    want = json.loads(old.lstrip(BOM))
    want["extraKnownMarketplaces"]["casefile"]["autoUpdate"] = True
    assert json.loads(new.lstrip(BOM)) == want
    removed, inserted = _single_edit(old, new)
    if name == "autoupdate_true":
        assert new == old, "уже включено — файл не пишется"
    elif name == "autoupdate_false":
        assert new == old.replace('"autoUpdate": false', '"autoUpdate": true')
    else:
        assert removed == "", removed
        assert re.sub(r"\s", "", inserted) == ',"autoUpdate":true', inserted
    if name == "crlf":
        assert "\n" not in new.replace("\r\n", ""), "концы строк файла не смешиваются"
    if name == "bom":
        assert new.startswith(BOM)


@pytest.mark.parametrize("tool", SETTINGS_TOOLS)
@pytest.mark.parametrize("name", SETTINGS_VECTORS)
def test_drop_cuts_out_the_declaration_and_nothing_else(
    tmp_path: Path, tool: str, name: str
) -> None:
    old = SETTINGS_VECTORS[name]
    code, new = _edit_settings(tmp_path, tool, "drop", old)

    assert code == 0
    if name in NO_CASEFILE:
        assert new == old
        return
    want = json.loads(old.lstrip(BOM))
    del want["extraKnownMarketplaces"]["casefile"]
    assert json.loads(new.lstrip(BOM)) == want
    removed, inserted = _single_edit(old, new)
    assert inserted == "" and "casefile" in removed, (removed, inserted)


def test_the_settings_edit_without_node_and_python_is_a_refusal_not_a_rewrite(
    tmp_path: Path,
) -> None:
    """Только jq (он пересобирает файл целиком) не годится: отказ, файл не тронут."""
    work = tmp_path / "bare"
    (work / "claude").mkdir(parents=True)
    (work / "bin").mkdir()
    settings = work / "claude" / "settings.json"
    settings.write_text(SETTINGS_VECTORS["indent2"], encoding="utf-8")
    for name in ("cmp", "cat", "mktemp"):
        (work / "bin" / name).symlink_to(shutil.which(name) or "")
    script = (
        "set -eu\n"
        + _shell_functions("claude_settings_file", "claude_settings")
        + "\nskill_tmp=$(mktemp -d)\nclaude_settings auto_update\n"
    )
    done = subprocess.run(
        ["/bin/sh", "-c", script],
        env={
            "PATH": str(work / "bin"),
            "HOME": str(work),
            "CLAUDE_CONFIG_DIR": str(work / "claude"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert done.returncode == 1
    assert settings.read_text(encoding="utf-8") == SETTINGS_VECTORS["indent2"]


def _backup_once(tmp_path: Path, target: Path, *, cp: str | None = None) -> tuple[int, str]:
    bin_dir = tmp_path / "bin-backup"
    bin_dir.mkdir(exist_ok=True)
    if cp is not None:
        (bin_dir / "cp").write_text(cp, encoding="utf-8")
        (bin_dir / "cp").chmod(0o755)
    script = (
        "set -eu\n"
        + _shell_functions("skill_line", "backup_once")
        + f'\nbackup_once Label "{target}"\n'
    )
    done = subprocess.run(
        ["/bin/sh", "-c", script],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done.returncode, done.stdout


def test_backup_once_keeps_the_first_original_and_the_permissions(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text("first", encoding="utf-8")
    target.chmod(0o600)
    code, out = _backup_once(tmp_path, target)
    bak = tmp_path / "settings.json.casefile-bak"

    assert code == 0 and bak.read_text(encoding="utf-8") == "first"
    assert bak.stat().st_mode & 0o777 == 0o600, "копия не читается всеми, как и сам файл"
    assert "saved a copy of" in out and "never overwritten" in out

    target.write_text("second", encoding="utf-8")
    code, out = _backup_once(tmp_path, target)
    assert code == 0 and bak.read_text(encoding="utf-8") == "first" and out == ""


def test_backup_once_has_nothing_to_copy_without_a_file_and_fails_when_it_cannot(
    tmp_path: Path,
) -> None:
    code, out = _backup_once(tmp_path, tmp_path / "absent.json")
    assert code == 0 and out == "" and not list(tmp_path.glob("*.casefile-bak"))

    target = tmp_path / "config.toml"
    target.write_text("x", encoding="utf-8")
    code, out = _backup_once(tmp_path, target, cp="#!/bin/sh\nexit 1\n")
    assert code == 1 and "could not save a copy of" in out
    assert not (tmp_path / "config.toml.casefile-bak").exists()


# Близнец в install.ps1: pwsh в образе нет, поэтому шаги стерегутся текстом, а сам сканер
# JSON прогнан на этих же 14 текстах в контейнере PowerShell 7 и дал те же байты, что node и
# python3 (заметка в `docs/notes/docker.md`).


def test_install_ps1_carries_the_consent_the_copies_and_the_point_edit() -> None:
    text = _read(INSTALL_PS1)

    for step in (
        "CASEFILE_PLUGIN_AUTOUPDATE",
        "function Confirm-SkillStep",
        "function Test-CanAsk",
        "Read-Host",
        "[Console]::IsInputRedirected",
        "function Backup-Once",
        ".casefile-bak",
        "function Update-ClaudeSettings",
        "function Edit-ClaudeSettingsText",
        "Install the plugin and make these changes? [y/N]",
        "Skipped: no file of another program was touched",
        "CASEFILE_SKILL=1 is set: going ahead without asking",
        "No terminal to ask on, so it goes ahead",
        "automatic updates not switched on, as CASEFILE_PLUGIN_AUTOUPDATE=0 says",
    ):
        assert step in text, f"install.ps1 не содержит {step!r}"
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "ConvertTo-Json" not in code, "settings.json больше не пересобирается целиком"


def test_both_installers_ask_before_the_plugin_step_and_copy_before_any_harness_command() -> None:
    sh_text, ps1_text = _read(INSTALL_SH), _read(INSTALL_PS1)

    assert sh_text.index("if ! skill_consent; then") < sh_text.index("for harness in claude")
    assert ps1_text.index("if (-not (Confirm-SkillStep)) { return }") < ps1_text.index(
        "@{ Exe = 'claude'"
    )
    claude_sh = sh_text[sh_text.index("skill_claude() {") :]
    assert claude_sh.index('backup_once "Claude Code"') < claude_sh.index("claude_marketplace_add")
    codex_sh = sh_text[sh_text.index("skill_codex() {") :]
    assert codex_sh.index('backup_once "Codex"') < codex_sh.index("codex_marketplace_add")
    claude_ps1 = ps1_text[ps1_text.index("function Install-ClaudeSkill") :]
    assert claude_ps1.index("Backup-Once 'Claude Code'") < claude_ps1.index(
        "Add-ClaudeMarketplace $src"
    )
    codex_ps1 = ps1_text[ps1_text.index("function Install-CodexSkill") :]
    assert codex_ps1.index("Backup-Once 'Codex'") < codex_ps1.index("Add-CodexMarketplace)")
    assert "command -v jq" not in sh_text, "jq пересобирает settings.json целиком"


def test_the_new_variables_are_described_where_people_look() -> None:
    for path in (INSTALL_SH, INSTALL_PS1, PROJECT_ROOT / "README.md", AGENT_GUIDE):
        text = _read(path)
        assert "CASEFILE_PLUGIN_AUTOUPDATE" in text, path.name
        assert ".casefile-bak" in text, path.name


# --- Автообновление сервера названо до установки и после неё (TRK-548) ------------------------
#
# Служба `updater` по умолчанию обновляет установку сама и держит для этого сокет Docker.
# Человек должен прочесть об этом, пока ещё может остановиться, и в итоге, вместе с тем, как
# это выключить. Решение владельца (TRK-548#6): автообновление остаётся, переключатель остаётся.

SOCKET = "/var/run/docker.sock"
AUTO_UPDATE_OFF = "CASEFILE_AUTO_UPDATE=false"
#: Правка `.env` вступает в силу, когда обновлятор пересоздан: переменную читает его
#: скрипт, а в окружение она попадает при создании контейнера. Той же командой
#: `scripts/check-auto-update.sh` (фаза E) переключает его в живой проверке.
RESTART_UPDATER = "docker compose up -d --no-deps updater"
INTRO = "Casefile updates itself."
OUTRO = "Updates arrive by themselves"
OFF_INTRO = "Auto-update is off in this installation"
OFF_OUTRO = "Auto-update is off (CASEFILE_AUTO_UPDATE=false"
ENV_OFF = "COMPOSE_FILE=docker-compose.prod.yml\nCASEFILE_AUTO_UPDATE=false\n"


def test_the_installer_says_before_it_installs_that_it_updates_itself(tmp_path: Path) -> None:
    done, _ = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    out = done.stdout
    intro = out[out.index(INTRO) : out.index("Installing Casefile into")]
    assert SOCKET in intro, "строка до установки не называет сокет Docker"
    assert AUTO_UPDATE_OFF in intro
    assert f"{tmp_path / 'casefile' / '.env'}" in intro, "не названо, какой файл править"
    assert RESTART_UPDATER in intro, "не названо, что перезапустить"
    assert OFF_INTRO not in out and OFF_OUTRO not in out


def test_the_intro_comes_before_anything_is_created_or_downloaded() -> None:
    """Каталога ещё нет, образов ещё нет: человек может остановиться, ничего не получив."""
    text = _read(INSTALL_SH)
    main = text[text.index("main() {") :]

    assert main.index("Docker is not running") < main.index("auto_update_intro\n")
    assert main.index("auto_update_intro\n") < main.index('mkdir -p "$DIR"')
    assert main.index("auto_update_intro\n") < main.index("docker pull")


def test_the_final_output_repeats_it_with_the_command_to_turn_it_off(tmp_path: Path) -> None:
    done, _ = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert out.index("Tell your agent what to do:") < out.index(OUTRO)
    outro = out[out.index(OUTRO) :]
    assert SOCKET in outro and AUTO_UPDATE_OFF in outro and RESTART_UPDATER in outro
    assert f"Files and data: {tmp_path / 'casefile'}" in outro


def test_an_installation_with_auto_update_off_is_not_told_that_it_updates_itself(
    tmp_path: Path,
) -> None:
    """Повторный запуск у того, кто выключил: «обновляется само» было бы неправдой."""
    done, _ = _install(tmp_path, dotenv=ENV_OFF)

    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert OFF_INTRO in out and OFF_OUTRO in out
    assert INTRO not in out and OUTRO not in out
    assert "running this installer again" in out, "не сказано, чем обновляться"
    assert "delete that line" in out and RESTART_UPDATER in out, "не сказано, как включить"


@pytest.mark.parametrize(
    "dotenv",
    [
        "CASEFILE_AUTO_UPDATE=False\n",
        "CASEFILE_AUTO_UPDATE=0\n",
        "CASEFILE_AUTO_UPDATE=\n",
        "CASEFILE_AUTO_UPDATE=true\n",
        "CASEFILE_AUTO_UPDATE=false\nCASEFILE_AUTO_UPDATE=true\n",
        "# CASEFILE_AUTO_UPDATE=false\n",
    ],
)
def test_only_an_exact_false_in_env_means_off_as_the_updater_reads_it(
    tmp_path: Path, dotenv: str
) -> None:
    """Служба сверяет значение с `false` дословно, последняя строка `.env` побеждает."""
    done, _ = _install(tmp_path, dotenv=f"COMPOSE_FILE=docker-compose.prod.yml\n{dotenv}")

    assert done.returncode == 0, done.stderr
    assert INTRO in done.stdout and OUTRO in done.stdout
    assert OFF_INTRO not in done.stdout


def test_the_updater_compares_the_switch_with_an_exact_false() -> None:
    """Слова установщиков и README «точное `false`» держатся на этой строке compose-файла."""
    compose = _read(PROJECT_ROOT / "docker-compose.prod.yml")
    assert '[ "$$CASEFILE_AUTO_UPDATE" = "false" ]' in compose


def test_skill_only_says_nothing_about_updating_a_server_that_is_not_there(
    tmp_path: Path,
) -> None:
    """При `CASEFILE_SKILL_ONLY=1` сервера на машине нет, и его автообновления тоже."""
    done, _ = _install(tmp_path, extra_env={"CASEFILE_SKILL_ONLY": "1"})

    assert done.returncode == 0, done.stderr
    for phrase in (INTRO, OUTRO, OFF_INTRO, OFF_OUTRO, SOCKET, "updater"):
        assert phrase not in done.stdout, phrase


def test_install_ps1_says_the_same_before_and_after() -> None:
    text = _read(INSTALL_PS1)

    for phrase in (
        INTRO,
        OUTRO,
        OFF_INTRO,
        OFF_OUTRO,
        SOCKET,
        AUTO_UPDATE_OFF,
        RESTART_UPDATER,
        "delete that line",
        "running this installer again",
    ):
        assert phrase in text, f"install.ps1 не содержит {phrase!r}"
    assert text.index("Docker is not running") < text.index("Write-AutoUpdateIntro\n")
    assert text.index("Write-AutoUpdateIntro\n") < text.index(
        "New-Item -ItemType Directory -Force -Path $Dir"
    )
    assert text.rstrip().endswith("Write-AutoUpdateOutro"), "итог — последняя строка установщика"
    assert text.index("if ($SkillOnly)") < text.index("Write-AutoUpdateIntro\n"), (
        "режим только скила уходит раньше: про автообновление сервера он молчит"
    )
    assert "-ceq 'false'" in text, "PowerShell сравнивает без учёта регистра, служба — дословно"


def test_the_readme_and_the_guide_name_the_socket_and_the_way_to_turn_it_off() -> None:
    for path in (PROJECT_ROOT / "README.md", AGENT_GUIDE):
        text = _read(path)
        assert "updater" in text and AUTO_UPDATE_OFF in text, path.name
        assert RESTART_UPDATER in text, f"{path.name}: не названо, что перезапустить"
    readme = _read(PROJECT_ROOT / "README.md")
    assert SOCKET in readme, "README не говорит, что служба держит сокет Docker"
    assert "TRACKER_RELEASE_CHECK=false" in readme, "README не называет выключатель плашки"
    assert "docker socket" in _read(AGENT_GUIDE).lower()


# --- Claude Desktop: расширение casefile.mcpb (TRK-514) ---------------------------------
#
# Чат Claude Desktop получает Casefile расширением `casefile.mcpb` из выпуска GitHub: шаг
# установщика его скачивает и открывает, а ставит сам Desktop по щелчку человека. Здесь
# `curl`, `open` и `uname` — заглушки: настоящий `open` поставил бы расширение в Desktop
# машины, на которой идёт набор.

MCPB_LATEST = "https://github.com/azimov777/casefile/releases/latest/download/casefile.mcpb"
DESKTOP = ("Library", "Application Support", "Claude")

FAKE_CURL = r"""#!/bin/sh
echo "curl $*" >>"$CALLS"
if [ -n "${FAIL_CURL:-}" ]; then
  echo "curl: (22) The requested URL returned error: 404" >&2
  exit 22
fi
out=
while [ $# -gt 0 ]; do
  case "$1" in -o) out=$2; shift 2 ;; *) shift ;; esac
done
printf 'PK fake mcpb' >"$out"
"""
FAKE_OPEN = r"""#!/bin/sh
echo "open $*" >>"$CALLS"
[ -f "$1" ] || exit 1
exit "${OPEN_EXIT:-0}"
"""


def _desktop_env(tmp_path: Path, *, desktop: bool = True, **extra: str) -> dict[str, str]:
    """Заглушки `curl`, `open` и `uname` (Darwin) и папка поддержки Claude Desktop в `HOME`."""
    stubs = tmp_path / "desktop-stubs"
    stubs.mkdir()
    for name, body in {
        "curl": FAKE_CURL,
        "open": FAKE_OPEN,
        "uname": "#!/bin/sh\necho Darwin\n",
    }.items():
        (stubs / name).write_text(body, encoding="utf-8")
        (stubs / name).chmod(0o755)
    if desktop:
        support = tmp_path.joinpath(*DESKTOP)
        support.mkdir(parents=True)
        # Чужой файл Desktop: шаг его не трогает (сверка байтов в тестах ниже).
        (support / "claude_desktop_config.json").write_text(
            '{"mcpServers": {"davinci-resolve": {"command": "x"}}}\n', encoding="utf-8"
        )
    python_dir = Path(shutil.which("python3") or "/usr/bin/python3").parent
    return {"PATH": f"{tmp_path / 'bin'}:{stubs}:/usr/bin:/bin:{python_dir}", **extra}


def _installed_extension(tmp_path: Path, version: str) -> None:
    """Расширение, которое Desktop распаковал: его манифест — наш, с адресом репозитория.

    Раскладка настоящая: у владельца (TRK-514#34) Desktop 2.19675.0 положил расширение в
    `Claude Extensions/local.mcpb.azimov777.tracker/manifest.json`, и `grep -l azimov777/casefile`
    по `Claude Extensions/*/manifest.json` нашёл ровно этот один файл.
    """
    manifest = json.loads((PROJECT_ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    target = tmp_path.joinpath(*DESKTOP, "Claude Extensions", "local.mcpb.azimov777.tracker")
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _desktop_calls(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith(("curl ", "open "))]


def test_skill_only_downloads_the_extension_and_opens_it_for_claude_desktop(
    tmp_path: Path,
) -> None:
    """Без терминала шаг идёт (TRK-546): файл выпуска скачан в «Загрузки» и открыт; адрес
    сервера назван для поля формы; чужой `claude_desktop_config.json` не тронут."""
    (tmp_path / "Downloads").mkdir()
    env = _desktop_env(tmp_path, CASEFILE_SKILL_ONLY="1", CASEFILE_URL=SERVER)
    config = tmp_path.joinpath(*DESKTOP, "claude_desktop_config.json")
    before = config.read_bytes()

    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    file = tmp_path / "Downloads" / "casefile.mcpb"
    assert _desktop_calls(calls) == [
        f"curl -fsSL -o {file}.download {MCPB_LATEST}",
        f"open {file}",
    ]
    assert file.read_bytes() == b"PK fake mcpb" and not file.with_suffix(".mcpb.download").exists()
    out = done.stdout
    assert f"casefile.mcpb is downloaded to {file} and opened" in out, "строка в списке согласия"
    assert re.search(rf"Claude Desktop +opened {re.escape(str(file))}: click Install", out)
    assert f"put {SERVER} into its address field" in out
    assert config.read_bytes() == before
    assert not list(tmp_path.rglob("*.casefile-bak"))


def test_the_full_install_puts_the_extension_of_its_release_into_its_directory(
    tmp_path: Path,
) -> None:
    """Полная установка: файл названного выпуска — в каталог установки, адрес по умолчанию."""
    env = _desktop_env(tmp_path, CASEFILE_VERSION="0.9.4")

    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    file = tmp_path / "casefile" / "casefile.mcpb"
    release = "https://github.com/azimov777/casefile/releases/download/v0.9.4/casefile.mcpb"
    assert _desktop_calls(calls) == [f"curl -fsSL -o {file}.download {release}", f"open {file}"]
    assert "keep the address it shows (http://127.0.0.1:8100/mcp)" in done.stdout
    assert "Casefile is running." in done.stdout


def test_an_installed_extension_is_not_downloaded_or_opened_again(tmp_path: Path) -> None:
    """Повтор не плодит записей: стоящее расширение узнаётся по манифесту, файл не открывается."""
    env = _desktop_env(tmp_path, CASEFILE_SKILL_ONLY="1", CASEFILE_URL=SERVER)
    _installed_extension(tmp_path, "0.9.4")

    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    assert _desktop_calls(calls) == []
    assert re.search(r"Claude Desktop +has the Casefile extension \(0\.9\.4\)", done.stdout)
    assert "casefile.mcpb is downloaded" not in done.stdout, "в списке согласия не названо"


def test_without_node_the_extension_is_set_up_all_the_same(tmp_path: Path) -> None:
    """Node.js человеку не нужен: расширение идёт на среде Node внутри Desktop."""
    env = _desktop_env(tmp_path, CASEFILE_SKILL_ONLY="1", CASEFILE_URL=SERVER)
    assert shutil.which("node", path=env["PATH"]) is None
    assert shutil.which("npx", path=env["PATH"]) is None

    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    assert [c.split()[0] for c in _desktop_calls(calls)] == ["curl", "open"]
    assert "Node.js is not needed" in done.stdout
    assert re.search(r"Other agents +npx not found", done.stdout)


@pytest.mark.parametrize(
    ("failure", "line"),
    [
        ({"FAIL_CURL": "1"}, f"could not download {MCPB_LATEST} - download it and double-click it"),
        ({"OPEN_EXIT": "1"}, "could not open "),
    ],
    ids=["download", "open"],
)
def test_a_failed_download_or_open_is_a_line_and_the_install_goes_on(
    tmp_path: Path, failure: dict[str, str], line: str
) -> None:
    env = _desktop_env(tmp_path, **failure)

    done, _ = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert re.search(rf"Claude Desktop +{re.escape(line)}", out), out
    assert "Settings > Extensions > Advanced settings > Install Extension..." in out
    assert "Casefile is running." in out and "Any other MCP client" in out
    assert not (tmp_path / "casefile" / "casefile.mcpb.download").exists()


@pytest.mark.parametrize("refusal", ["skill-zero", "answer-n"])
def test_skill_zero_or_n_leaves_claude_desktop_alone(tmp_path: Path, refusal: str) -> None:
    extra = {"CASEFILE_SKILL": "0"} if refusal == "skill-zero" else _terminal(tmp_path, "n\n")
    env = _desktop_env(tmp_path, **extra)

    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    assert _desktop_calls(calls) == []
    assert not (tmp_path / "casefile" / "casefile.mcpb").exists()


def test_without_an_address_claude_desktop_is_not_set_up(tmp_path: Path) -> None:
    """`CASEFILE_SKILL_ONLY=1` без адреса ставит плагин ради скила; расширению нужен сервер."""
    env = _desktop_env(tmp_path, CASEFILE_SKILL_ONLY="1")

    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    assert _desktop_calls(calls) == []
    assert re.search(r"Claude Desktop +not set up: it needs your server's address", done.stdout)


def test_a_mac_without_claude_desktop_says_not_found(tmp_path: Path) -> None:
    env = _desktop_env(tmp_path, desktop=False, CASEFILE_SKILL_ONLY="1", CASEFILE_URL=SERVER)

    done, calls = _install(tmp_path, extra_env=env)

    assert done.returncode == 0, done.stderr
    assert _desktop_calls(calls) == []
    assert re.search(r"Claude Desktop +not found", done.stdout)


def test_casefile_mcpb_url_names_the_file_to_download(tmp_path: Path) -> None:
    own = "https://example.test/casefile.mcpb"
    env = _desktop_env(
        tmp_path, CASEFILE_SKILL_ONLY="1", CASEFILE_URL=SERVER, CASEFILE_MCPB_URL=own
    )

    _, calls = _install(tmp_path, extra_env=env)

    assert _desktop_calls(calls)[0].endswith(f".download {own}")


def test_both_installers_and_the_guide_name_the_same_extension_file_and_steps() -> None:
    sh_text, ps1_text, guide = _read(INSTALL_SH), _read(INSTALL_PS1), _read(AGENT_GUIDE)
    for text in (sh_text, ps1_text, guide):
        assert MCPB_LATEST in text
        assert "Settings > Extensions > Advanced settings > Install Extension..." in text
    for text in (sh_text, ps1_text):
        assert "CASEFILE_MCPB_URL" in text
        assert "releases/download/v" in text
        assert "claude_desktop_config.json is not touched" in text
    assert 'skill_run open "$MCPB_FILE"' in sh_text
    assert "Start-Process -FilePath $script:McpbFile" in ps1_text
    assert "LocalCache\\Roaming\\Claude" in ps1_text and "Get-DesktopDirs" in ps1_text


# --- Снимок базы перед `up` (TRK-654) -----------------------------------------------------

#: Что отвечает подставной `compose config`: образ `api`, как его читает установщик.
SNAPSHOT_CONFIG = (
    "services:\n  api:\n    image: ghcr.io/x/casefile:1\n  ui:\n    image: ghcr.io/x/ui:1\n"
)


def _snapshot_scene(**over: str) -> dict[str, str]:
    """Существующая установка: контейнер базы есть, база на `rev1`, образ несёт `rev2`."""
    scene = {
        "db": "container-db\n",
        "revision": "rev1\n",
        "config": SNAPSHOT_CONFIG,
        "head": "rev2 (head)\n",
    }
    scene.update(over)
    return scene


def _install_in(
    root: Path, name: str, **scene: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    (root / name).mkdir()
    return _install(root / name, **scene)


def _snapshot_index(calls: list[str]) -> int:
    return next(i for i, c in enumerate(calls) if "pg_dump" in c)


def test_an_existing_database_with_another_head_gets_a_snapshot_before_up(tmp_path: Path) -> None:
    """Образ несёт другую ревизию, чем база: снимок в том же томе и под тем же именем, до `up`."""
    done, calls = _install(tmp_path, **_snapshot_scene())

    assert done.returncode == 0, done.stderr
    assert "-Fc" in calls[_snapshot_index(calls)]
    store = next(c for c in calls if "--entrypoint sh updater" in c)
    assert "/snapshot/before-update.dump" in store
    assert calls.index(store) > _snapshot_index(calls)
    assert calls.index(store) < calls.index("compose up -d --remove-orphans")
    assert (tmp_path / "scene" / "snapshot").read_text() == "dump-bytes\n"
    assert "rev1 -> rev2" in done.stdout


def test_an_existing_database_with_the_same_head_gets_no_snapshot(tmp_path: Path) -> None:
    done, calls = _install(tmp_path, **_snapshot_scene(head="rev1 (head)\n"))

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if "pg_dump" in c or "--entrypoint sh updater" in c]
    assert "compose up -d --remove-orphans" in calls


def test_a_first_install_and_an_empty_database_get_no_snapshot(tmp_path: Path) -> None:
    for name, scene in (("first", {}), ("empty", _snapshot_scene(revision="no-table\n"))):
        done, calls = _install_in(tmp_path, name, **scene)
        assert done.returncode == 0, done.stderr
        assert not [c for c in calls if "pg_dump" in c], name


def test_an_unreadable_revision_or_head_is_taken_as_a_change_and_gets_a_snapshot(
    tmp_path: Path,
) -> None:
    for name, scene in (
        ("db", _snapshot_scene(revision="")),
        ("image", _snapshot_scene(head="")),
    ):
        done, calls = _install_in(tmp_path, name, **scene)
        assert done.returncode == 0, done.stderr
        assert [c for c in calls if "pg_dump" in c], name
        assert "could not read the" in done.stdout, name


def test_a_failed_snapshot_stops_the_installer_before_up(tmp_path: Path) -> None:
    """Сбой `pg_dump` или записи в том — `up` не вызван, обновлятор поднят снова."""
    for name, scene in (("dump", {"dump": "fail"}), ("store", {"store": "1"})):
        done, calls = _install_in(
            tmp_path, name, updater="container-updater\n", **_snapshot_scene(**scene)
        )
        assert done.returncode != 0, name
        assert "could not take a snapshot of the database" in done.stderr, name
        assert not [c for c in calls if c.startswith("compose up ")], name
        assert calls[-1] == "start container-updater", name


def test_a_database_volume_without_a_db_container_gets_the_db_up_and_a_snapshot(
    tmp_path: Path,
) -> None:
    """После `down` без `-v`: том есть, контейнера нет, head другой.

    Порядок: `up db`, снимок, потом `up`.
    """
    done, calls = _install(tmp_path, **_snapshot_scene(db="", volume="casefile_pgdata\n"))

    assert done.returncode == 0, done.stderr
    up_db = calls.index("compose up -d --wait db")
    assert up_db < _snapshot_index(calls)
    store = next(c for c in calls if "--entrypoint sh updater" in c)
    up_all = calls.index("compose up -d --remove-orphans")
    assert _snapshot_index(calls) < calls.index(store) < up_all
    assert "rev1 -> rev2" in done.stdout


def test_no_database_volume_is_a_first_install_without_a_snapshot(tmp_path: Path) -> None:
    done, calls = _install(tmp_path, **_snapshot_scene(db="", volume=""))

    assert done.returncode == 0, done.stderr
    assert not [c for c in calls if "pg_dump" in c or "up -d --wait db" in c]
    assert "compose up -d --remove-orphans" in calls


def test_a_db_that_does_not_start_over_an_existing_volume_stops_before_up(tmp_path: Path) -> None:
    done, calls = _install(tmp_path, **_snapshot_scene(db="", volume="v\n", up="1"))

    assert done.returncode != 0
    assert "did not start" in done.stderr
    assert "compose up -d --remove-orphans" not in calls


def test_install_ps1_starts_the_db_over_an_existing_volume() -> None:
    text = _read(INSTALL_PS1)
    body = text[text.index("function Invoke-SnapshotBeforeUp") :]

    assert "com.docker.compose.volume=pgdata" in body
    assert body.index("volume ls") < body.index("up -d --wait db") < body.index("pg_dump")


def test_install_ps1_takes_the_same_snapshot_before_up() -> None:
    text = _read(INSTALL_PS1)
    compose = _read(INSTALL_SH.parent / "docker-compose.prod.yml")
    sql = re.search(r'SNAPSHOT_REVISION_SQL="(.*)"', _read(INSTALL_SH)).group(1)  # type: ignore[union-attr]

    assert sql in text, "the revision query differs between the installers"
    assert sql.replace("'", "'\"'\"'") in compose, "the revision query differs from the updater one"
    assert "before-update.dump" in text and "updater-snapshot" in text
    assert text.index("Invoke-Docker compose pull") < text.index("Invoke-SnapshotBeforeUp\n")
    assert text.rindex("Invoke-SnapshotBeforeUp") < text.index("Invoke-Docker compose up")
