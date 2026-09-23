"""Автообновление установки: канал выпусков, цикл обновлятора и замена самого обновлятора.

Установка стоит на канале выпусков `stable` и раз в час сверяет его (TRK-119). Живьём
цикл проверяется локальным реестром (`scripts/check-auto-update.sh`); здесь — то, что
проверяется без Docker: умолчания контура, публикация канала конвейером, compose-файл в
образе выпуска и сам сценарий обновлятора, исполненный оболочкой против подставного
`docker`, который записывает вызовы и отвечает по сценарию теста.
"""

import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest
from tests.test_compose import COMPOSE_FILES, PROJECT_ROOT, _indent, _services

PROD = COMPOSE_FILES["prod"]
IMAGES_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "images.yml"
DOCKERFILE_PROD = PROJECT_ROOT / "docker" / "Dockerfile.prod"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"
INSTALLERS = (PROJECT_ROOT / "install.sh", PROJECT_ROOT / "install.ps1")
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"

#: Метка ревизии обновлятора и якорь, из которого её берут обе службы.
REVISION_LABEL = "casefile.updater.revision"
REVISION_ANCHOR = "x-updater-revision: &updater-revision"

#: Где compose-файл лежит в образе выпуска.
COMPOSE_IN_IMAGE = "/app/docker-compose.prod.yml"

#: Сняты заменой (правило замены очереди TRK): compose-файл больше не берётся по адресу.
REMOVED_VARIABLES = ("CASEFILE_COMPOSE_URL", "CASEFILE_SOURCE")


def _prod() -> str:
    return PROD.read_text(encoding="utf-8")


def _script(service: str) -> str:
    """Сценарий оболочки службы — блок `- |` её команды, с долларами для оболочки."""
    lines = _services(_prod())[service]
    start = next(n for n, line in enumerate(lines) if line.strip() == "- |")
    base = _indent(lines[start])
    body: list[str] = []
    for line in lines[start + 1 :]:
        if _indent(line) <= base:
            break
        body.append(line)
    depth = min(_indent(line) for line in body)
    return "\n".join(line[depth:] for line in body).replace("$$", "$") + "\n"


def _revision() -> str:
    """Хеш определения `updater` без самой метки: комментарии в него не входят."""
    lines = [line for line in _services(_prod())["updater"] if REVISION_LABEL not in line]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]


def test_the_installation_follows_the_release_channel_by_default() -> None:
    """Обе службы Casefile по умолчанию на `stable`, а не на `latest` коммитов main."""
    text = _prod()

    assert text.count("${CASEFILE_VERSION:-stable}") == 2
    assert "${CASEFILE_VERSION:-latest}" not in text


def test_the_updater_checks_every_hour_by_default() -> None:
    assert "CASEFILE_UPDATE_INTERVAL: ${CASEFILE_UPDATE_INTERVAL:-1}" in _prod()
    assert "CASEFILE_AUTO_UPDATE: ${CASEFILE_AUTO_UPDATE:-true}" in _prod()


def test_the_updater_revision_matches_its_definition() -> None:
    """Поменял службу `updater` — поменяй метку, иначе установки её не получат.

    `updater-renew` заменяет обновлятор, только когда его метка не та, что в файле.
    """
    text = _prod()
    anchors = [line for line in text.splitlines() if line.startswith(REVISION_ANCHOR)]

    assert len(anchors) == 1, f"якорь `{REVISION_ANCHOR}` должен быть ровно один"
    assert f"{REVISION_LABEL}: *updater-revision" in "\n".join(_services(text)["updater"])
    assert "CASEFILE_UPDATER_REVISION: *updater-revision" in "\n".join(
        _services(text)["updater-renew"]
    )
    assert anchors[0] == f'{REVISION_ANCHOR} "{_revision()}"', (
        f'определение `updater` изменилось: поставь `{REVISION_ANCHOR} "{_revision()}"`'
    )


def test_every_up_of_the_application_runs_the_renewal() -> None:
    """`up -d db api mcp ui` обновлятора прежнего выпуска запускает `updater-renew`."""
    ui = "\n".join(_services(_prod())["ui"])

    assert "updater-renew:\n        condition: service_started\n        required: false" in ui


def test_the_release_image_carries_the_compose_file() -> None:
    dockerfile = DOCKERFILE_PROD.read_text(encoding="utf-8")
    ignored = DOCKERIGNORE.read_text(encoding="utf-8").split()

    assert "COPY --chown=tracker:tracker docker-compose.prod.yml ./" in dockerfile
    assert "WORKDIR /app" in dockerfile
    assert "docker-compose.prod.yml" not in ignored
    assert COMPOSE_IN_IMAGE in _script("updater")
    for installer in INSTALLERS:
        assert "/app/$" in installer.read_text(encoding="utf-8"), installer.name


def test_the_compose_file_is_no_longer_taken_from_an_address() -> None:
    for path in (PROD, ENV_EXAMPLE, *INSTALLERS):
        text = path.read_text(encoding="utf-8")
        for name in REMOVED_VARIABLES:
            assert name not in text, f"{path.name}: {name} снят заменой"


def test_a_release_tag_publishes_the_version_and_the_channel() -> None:
    """Тег `v*` — номер версии и `stable`; `latest` — только main, пре-релиз — не `stable`."""
    workflow = IMAGES_WORKFLOW.read_text(encoding="utf-8")

    assert 'tags: ["v*"]' in workflow
    assert "type=semver,pattern={{version}}" in workflow
    assert (
        "type=raw,value=stable,enable=${{ startsWith(github.ref, 'refs/tags/v') "
        "&& !contains(github.ref_name, '-') }}"
    ) in workflow
    assert "type=raw,value=latest,enable={{is_default_branch}}" in workflow
    assert "latest=false" in workflow


# --- Сценарий обновлятора против подставного `docker` ---------------------------------

#: Подставной `docker`: пишет каждый вызов в `$CALLS` и отвечает по файлам сценария.
FAKE_DOCKER = r"""#!/bin/sh
echo "$*" >>"$CALLS"
# Pops the first line of the scene file $1; prints $2 when there is none.
next() {
  if [ -s "$SCENE/$1" ]; then
    head -n 1 "$SCENE/$1"
    tail -n +2 "$SCENE/$1" >"$SCENE/$1.rest" && mv "$SCENE/$1.rest" "$SCENE/$1"
  else
    echo "$2"
  fi
}
case "$*" in
  "inspect -f {{index .Config.Labels \"com.docker.compose.project\"}} "*) echo test-project ;;
  "inspect -f {{index .Config.Labels \"casefile.updater.revision\"}} "*) cat "$SCENE/revision" ;;
  "inspect -f {{.Image}} "*) echo "$(cat "$SCENE/running")" ;;
  "compose ps -q "*) echo "container-$4" ;;
  "ps -q "*) echo container-updater ;;
  "inspect -f {{range .Mounts}}"*) cat "$SCENE/directory" ;;
  "compose pull"*) exit "$(cat "$SCENE/pull" 2>/dev/null || echo 0)" ;;
  "compose config")
    printf 'name: test\nservices:\n  api:\n    depends_on:\n      db:\n'
    printf '        condition: service_healthy\n    image: registry/casefile:stable\n'
    printf '  db:\n    image: postgres:17-alpine\n  mcp:\n    image: registry/casefile:stable\n'
    printf '  ui:\n    image: registry/casefile-ui:stable\n' ;;
  "compose -f "*) exit 0 ;;
  "image inspect -f {{.Id}} casefile-updater/"*)
    [ -s "$SCENE/failed" ] || exit 1
    cat "$SCENE/failed" ;;
  "image inspect -f {{.Id}} "*) echo "$(cat "$SCENE/wanted")" ;;
  "image inspect "*) echo 0.2.0 ;;
  "run "*) [ -s "$SCENE/compose-in-image" ] || exit 1; cat "$SCENE/compose-in-image" ;;
  "compose up "*) exit "$(next up 0)" ;;
  "inspect -f {{.State.Health.Status}} "*) next health healthy ;;
  "tag "*) exit 0 ;;
  "top "*)
    n=$(cat "$SCENE/busy" 2>/dev/null || echo 0)
    echo "PID COMMAND"
    echo "1 sh"
    if [ "$n" -gt 0 ]; then echo $((n - 1)) >"$SCENE/busy"; echo "7 docker"; fi ;;
  "rmi "*) exit 0 ;;
esac
"""


class Updater:
    """Каталог установки, подставной `docker` на `PATH` и запуск сценария службы."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.scene = root / "scene"
        self.scene.mkdir()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(FAKE_DOCKER, encoding="utf-8")
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        self.project = root / "project"
        self.project.mkdir()
        (self.project / "docker-compose.prod.yml").write_text("release: 1\n", encoding="utf-8")
        self.calls = root / "calls"
        self.calls.touch()
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "SCENE": str(self.scene),
            "COMPOSE_FILE": "docker-compose.prod.yml",
            "CASEFILE_AUTO_UPDATE": "true",
            "CASEFILE_UPDATE_INTERVAL": "1",
        }
        self.set(
            running="sha256:old",
            wanted="sha256:old",
            compose_in_image="release: 1\n",
            directory="/home/someone/casefile\n",
        )

    def set(self, **files: str) -> None:
        for name, value in files.items():
            (self.scene / name.replace("_", "-")).write_text(value, encoding="utf-8")

    def run(self, service: str, tail: str, **env: str) -> str:
        """Сценарий службы: с `tail` — только функции и заданный хвост вместо цикла."""
        script = _script(service).replace("/tmp/compose.yml", str(self.root / "fetched.yml"))
        script = script.replace("/tmp/previous-compose.yml", str(self.root / "previous.yml"))
        script = script.replace("sleep 5", "sleep 0")
        if tail:
            script = script[: script.index("trap 'exit 0' TERM INT")] + tail
        done = subprocess.run(
            ["sh", "-c", script],
            cwd=self.project,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout + done.stderr

    def called(self, prefix: str) -> list[str]:
        return [c for c in self.calls.read_text().splitlines() if c.startswith(prefix)]


@pytest.fixture
def updater(tmp_path: Path) -> Updater:
    return Updater(tmp_path)


def test_a_check_without_a_new_release_recreates_nothing(updater: Updater) -> None:
    out = updater.run("updater", "update\n")

    assert "already up to date" in out
    assert updater.called("compose pull")
    assert not updater.called("compose up")
    assert not updater.called("rmi")


def test_a_new_release_under_the_tag_is_brought_up(updater: Updater) -> None:
    updater.set(wanted="sha256:new")

    out = updater.run("updater", "update\n")

    assert updater.called("compose up") == ["compose up -d db api mcp ui"]
    assert "updated to 0.2.0" in out
    assert "rmi sha256:old" in updater.called("rmi")


def test_the_compose_file_of_the_release_replaces_the_local_one(updater: Updater) -> None:
    updater.set(compose_in_image="release: 2\n")

    out = updater.run("updater", "update\n")

    assert (updater.project / "docker-compose.prod.yml").read_text() == "release: 2\n"
    assert "compose file updated from registry/casefile:stable" in out
    assert len(updater.called("compose pull")) == 2, "новый файл может звать новые образы"
    assert updater.called("compose up")


#: Свои теги обновлятора в проекте подставного `docker`.
KEPT = "casefile-updater/test-project"


def test_the_previous_release_is_kept_under_its_own_tag_until_the_new_one_is_up(
    updater: Updater,
) -> None:
    updater.set(wanted="sha256:new")

    updater.run("updater", "update\n")

    calls = updater.calls.read_text().splitlines()
    kept = calls.index(f"tag sha256:old {KEPT}/api:previous")
    assert f"tag sha256:old {KEPT}/ui:previous" in calls
    assert kept < calls.index("compose up -d db api mcp ui")
    assert f"rmi {KEPT}/api:previous" in calls
    assert f"rmi {KEPT}/api:failed" in calls, "удачный выпуск снимает метку упавшего"
    assert not updater.called("compose up -d --no-deps")


def test_a_release_that_does_not_start_is_rolled_back(updater: Updater) -> None:
    """`up` упал: службы — на образы `previous`, упавший выпуск — под метку `failed`."""
    updater.set(wanted="sha256:new", up="1\n")

    out = updater.run("updater", "update\n")

    calls = updater.calls.read_text().splitlines()
    failed = calls.index(f"tag registry/casefile:stable {KEPT}/api:failed")
    assert f"tag registry/casefile-ui:stable {KEPT}/ui:failed" in calls
    back = calls.index(f"tag {KEPT}/api:previous registry/casefile:stable")
    assert f"tag {KEPT}/ui:previous registry/casefile-ui:stable" in calls
    assert failed < back, "метка `failed` ставится, пока под тегом ещё упавший выпуск"
    assert updater.called("compose up") == [
        "compose up -d db api mcp ui",
        "compose up -d --no-deps db api mcp ui",
    ], "откат идёт без `migrate`: прежний код не знает ревизии схемы нового"
    assert "failed to start" in out
    assert "rolled back to 0.2.0" in out
    assert f"rmi {KEPT}/api:previous" in calls
    assert f"rmi {KEPT}/api:failed" not in calls


def test_a_release_whose_services_stay_unhealthy_is_rolled_back(updater: Updater) -> None:
    """`up` прошёл, но mcp так и не стал здоровым — это тоже неудача."""
    updater.set(wanted="sha256:new", health="healthy\nunhealthy\nhealthy\n")

    out = updater.run("updater", "update\n")

    assert updater.called("compose up -d --no-deps db api mcp ui")
    assert "rolled back to 0.2.0" in out


def test_the_rollback_restores_the_compose_file_of_the_previous_release(
    updater: Updater,
) -> None:
    updater.set(compose_in_image="release: 2\n", up="1\n")

    updater.run("updater", "update\n")

    assert (updater.project / "docker-compose.prod.yml").read_text() == "release: 1\n"


def test_a_rollback_that_fails_too_names_the_version_to_go_back_to(updater: Updater) -> None:
    updater.set(wanted="sha256:new", up="1\n1\n")

    out = updater.run("updater", "update\n")

    assert "could not go back either" in out
    assert "put CASEFILE_VERSION=0.2.0 into .env" in out


def test_a_release_that_failed_here_is_not_tried_again(updater: Updater) -> None:
    """Под тегом тот же упавший выпуск: ни нового файла, ни `up`, теги — на работающий."""
    updater.set(wanted="sha256:bad", failed="sha256:bad\n", compose_in_image="release: 2\n")

    out = updater.run("updater", "update\n")

    assert "did not start here before" in out
    assert not updater.called("compose up")
    assert not updater.called("run ")
    assert (updater.project / "docker-compose.prod.yml").read_text() == "release: 1\n"
    assert updater.called("tag ") == [
        "tag sha256:old registry/casefile:stable",
        "tag sha256:old registry/casefile-ui:stable",
    ], "ручной `docker compose up` не должен поднять упавший выпуск"


def test_the_next_release_after_a_failed_one_is_brought_up(updater: Updater) -> None:
    updater.set(wanted="sha256:next", failed="sha256:bad\n")

    out = updater.run("updater", "update\n")

    assert updater.called("compose up") == ["compose up -d db api mcp ui"]
    assert "updated to 0.2.0" in out
    assert updater.called(f"rmi {KEPT}/api:failed")


def test_a_release_without_a_compose_file_keeps_the_local_one(updater: Updater) -> None:
    updater.set(compose_in_image="")

    out = updater.run("updater", "update\n")

    assert (updater.project / "docker-compose.prod.yml").read_text() == "release: 1\n"
    assert "no usable compose file" in out
    assert not updater.called("compose up")


def test_no_network_leaves_everything_as_it_is(updater: Updater) -> None:
    updater.set(pull="1", wanted="sha256:new")

    out = updater.run("updater", "update\n")

    assert "could not pull images" in out
    assert not updater.called("compose up")


def test_auto_update_off_does_not_even_pull(updater: Updater) -> None:
    script_head = "trap 'exit 0' TERM INT\n"
    out = updater.run(
        "updater",
        _script("updater")[_script("updater").index(script_head) :].replace(
            "while :; do sleep 86400 & wait $!; done", "exit 0", 1
        ),
        CASEFILE_AUTO_UPDATE="false",
    )

    assert "auto-update is off" in out
    assert not updater.called("compose pull")


@pytest.mark.parametrize(
    ("interval", "seconds"),
    [("1", 3600), ("2h", 7200), ("30m", 1800), ("90s", 90), ("0", 0), ("", 0), ("soon", 0)],
)
def test_the_interval_reads_hours_minutes_and_seconds(
    updater: Updater, interval: str, seconds: int
) -> None:
    out = updater.run("updater", "period\n", CASEFILE_UPDATE_INTERVAL=interval)

    assert out.strip() == str(seconds)


def test_the_renewal_replaces_a_busy_updater_of_an_earlier_release(updater: Updater) -> None:
    """Прежний обновлятор зовёт `up` сам: дождаться, пока кончит, и заменить его."""
    updater.set(revision="\n", busy="2")

    out = updater.run("updater-renew", "", CASEFILE_UPDATER_REVISION=_revision())

    assert "replacing the updater" in out
    [replace] = updater.called("run --rm -v /var/run/docker.sock")
    assert "-v /home/someone/casefile:/home/someone/casefile -w /home/someone/casefile" in replace
    assert replace.endswith("docker compose up -d --no-deps updater")


def test_the_renewal_gives_up_where_the_installation_path_is_unknown(updater: Updater) -> None:
    """Путь не того вида — не монтировать наугад, а сказать, как получить обновлятор."""
    updater.set(revision="\n", busy="1", directory="C:\\Users\\someone\\casefile\n")

    out = updater.run("updater-renew", "", CASEFILE_UPDATER_REVISION=_revision())

    assert "run the installer again" in out
    assert not updater.called("run ")


def test_the_renewal_leaves_an_idle_updater_to_whoever_runs_up(updater: Updater) -> None:
    """Обновлятор спит — `up` зовёт установщик или человек, и пересоздаст его сам."""
    updater.set(revision="\n", busy="0")

    updater.run("updater-renew", "", CASEFILE_UPDATER_REVISION=_revision())

    assert not updater.called("run ")


def test_the_renewal_leaves_a_current_updater_alone(updater: Updater) -> None:
    updater.set(revision=f"{_revision()}\n", busy="5")

    updater.run("updater-renew", "", CASEFILE_UPDATER_REVISION=_revision())

    assert not updater.called("run ")
    assert not updater.called("top")
