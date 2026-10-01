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
    }
    env.update(extra_env or {})
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
    "claude plugin marketplace add azimov777/casefile#stable --sparse .claude-plugin skills",
    "claude plugin install casefile@casefile --scope user",
    "codex plugin marketplace add azimov777/casefile --ref stable "
    "--sparse .claude-plugin --sparse .codex-plugin --sparse skills",
    "codex plugin add casefile@casefile",
    "hermes skills install azimov777/casefile/skills/casefile",
    "npx skills add azimov777/casefile#stable",
)

#: Строки подключения MCP ключом — теперь только у Hermes, харнесса без OAuth (TRK-452):
#: Claude Code и Codex подключает плагин, и токена для них установщик не печатает.
CONNECT_LINES = ("mcp_servers:",)


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
                r"""["']Hermes \(no OAuth""",
                r"""["']Any other MCP client""",
            )
        ]
        assert blocks == sorted(blocks)


def test_the_installer_prints_the_key_only_for_harnesses_without_oauth(
    tmp_path: Path,
) -> None:
    """Claude Code и Codex подключает плагин с входом OAuth: токена в их блоках нет.

    Ключ агента печатается Hermes и «прочим клиентам без OAuth», с путём, как прочитать его
    снова для сторожа журнала (TRK-452, TRK-469#25); ни в один файл он не пишется.
    """
    done, _ = _install(tmp_path)

    assert done.returncode == 0, done.stderr
    out = done.stdout
    for command in SKILL_COMMANDS:
        assert command in out, f"вывод установщика не содержит {command!r}"
    blocks = {
        "claude": out[out.index("Claude Code:") : out.index("Codex:")],
        "codex": out[out.index("Codex:") : out.index("Hermes (no OAuth")],
        "hermes": out[out.index("Hermes (no OAuth") : out.index("Any other MCP client")],
        "other": out[out.index("Any other MCP client") : out.index("The skill teaches")],
    }
    for name in ("claude", "codex"):
        assert "agent-token-secret" not in blocks[name] and "Bearer" not in blocks[name], name
        assert "http://localhost:8100/mcp" in blocks[name], name
    assert "claude mcp login plugin:casefile:casefile" in blocks["claude"]
    assert "codex mcp login casefile" in blocks["codex"]
    assert 'url: "http://localhost:8100/mcp"' in blocks["hermes"]
    assert 'Authorization: "Bearer agent-token-secret"' in blocks["hermes"]
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
FAKE_CLAUDE = r"""#!/bin/sh
echo "claude $*" >>"$CALLS"
case "$*" in
  "plugin marketplace add"*)
    mkdir -p "$CLAUDE_CONFIG_DIR"
    echo '{"extraKnownMarketplaces":{"casefile":{"source":{"source":"git","url":"u"}}}}' \
      >"$CLAUDE_CONFIG_DIR/settings.json" ;;
  "plugin install"*) [ -z "${FAIL_INSTALL:-}" ] || { echo "install refused" >&2; exit 1; } ;;
  "mcp get "*) [ -f "$SCENE/claude-$3" ] && cat "$SCENE/claude-$3" || exit 1 ;;
  "mcp login "*) exit "$(cat "$SCENE/login-claude" 2>/dev/null || echo 0)" ;;
  "plugin list")
    printf 'Installed plugins:\n\n  > casefile@casefile\n    Version: 0.7.1\n'
    printf '    Scope: user\n    Status: enabled\n' ;;
esac
"""
FAKE_CODEX = r"""#!/bin/sh
echo "codex $*" >>"$CALLS"
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
        "claude plugin marketplace add example/casefile#stable --sparse .claude-plugin skills",
        "claude plugin marketplace update casefile",
        f"claude plugin install casefile@casefile --scope user --config casefile_url={SERVER}",
        "claude plugin update casefile@casefile",
        "claude plugin list",
    ]
    assert (
        "codex plugin marketplace add example/casefile --ref stable "
        "--sparse .claude-plugin --sparse .codex-plugin --sparse skills"
    ) in calls
    assert "npx -y skills add example/casefile#stable -g -y --agent cursor" in calls
    assert re.search(r"Claude Code +installed 0\.7\.1 \(updates itself\)", done.stdout)
    assert re.search(r"Codex +installed 0\.7\.1", done.stdout)
    assert re.search(r"Hermes +not found", done.stdout)
    assert re.search(r"Other agents +installed", done.stdout)
    settings = (tmp_path / "claude" / "settings.json").read_text()
    assert '"autoUpdate": true' in settings


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
    tty.write_text("")
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
    tty.write_text("")
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
    tty.write_text("")
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
    "--sparse .codex-plugin",
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
    "Hermes (no OAuth: a key)",
)


def test_both_installers_carry_the_plugin_and_sign_in_steps() -> None:
    for name, text in (("install.sh", _read(INSTALL_SH)), ("install.ps1", _read(INSTALL_PS1))):
        for step in PLUGIN_STEPS:
            assert step in text, f"{name} не содержит {step!r}"
        # Прежние ручные записи убираются под обоими именами и только в своих областях.
        assert "'casefile', 'tracker'" in text or "casefile tracker" in text, name


def test_install_ps1_prints_no_token_in_the_claude_code_and_codex_blocks() -> None:
    for text in (_read(INSTALL_SH), _read(INSTALL_PS1)):
        start = re.search(r"""["']Claude Code:["']""", text).start()  # type: ignore[union-attr]
        end = text.index("Hermes (no OAuth: a key)")
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
    import pytest

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
