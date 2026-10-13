"""`scripts/run-locked.sh` под тестом: очередь тяжёлых прогонов с общим замком (TRK-706).

Замок и интервалы задаются переменными окружения, поэтому тесты не ждут по 30 секунд
и не трогают настоящий замок машины: у каждого теста свой каталог замка во временной папке.
"""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run-locked.sh"


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    return tmp_path / "run.lock"


def _env(lock: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["CASEFILE_RUN_LOCK"] = str(lock)
    env["CASEFILE_RUN_POLL"] = "0.2"
    env["CASEFILE_RUN_MAX_LOAD"] = "100000"
    env.update(extra)
    return env


def _start(lock: Path, *cmd: str, **extra: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(SCRIPT), *cmd],
        env=_env(lock, **extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_holder(lock: Path) -> list[str]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        holder = lock / "holder"
        if holder.exists():
            lines = holder.read_text(encoding="utf-8").splitlines()
            if len(lines) == 4:
                return lines
        time.sleep(0.05)
    raise AssertionError("holder не появился")


def test_exit_code_is_passed_through(lock: Path) -> None:
    result = subprocess.run(
        [str(SCRIPT), "sh", "-c", "exit 7"],
        env=_env(lock),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 7
    assert "RUN_EXIT=7" in result.stdout.splitlines()
    assert not lock.exists()


def test_second_call_waits_and_names_the_holder(lock: Path, tmp_path: Path) -> None:
    marker = tmp_path / "first-done"
    first = _start(lock, "sh", "-c", f"sleep 1.5; touch {marker}")
    lines = _wait_for_holder(lock)
    assert lines[0] == str(first.pid)
    second = _start(lock, "sh", "-c", f"test -e {marker} && echo second-after-first")
    out, _ = second.communicate(timeout=30)
    first.communicate(timeout=30)
    waiting = [ln for ln in out.splitlines() if ln.startswith("waiting for lock ")]
    assert waiting, out
    assert f"by pid {first.pid} in " in waiting[0]
    assert f"sleep 1.5; touch {marker}" in waiting[0]
    assert out.index("waiting for lock") < out.index("running:")
    assert "second-after-first" in out
    assert second.returncode == 0
    assert "RUN_EXIT=0" in out.splitlines()
    assert not lock.exists()


def test_stale_lock_is_removed_without_waiting(lock: Path) -> None:
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock.mkdir()
    (lock / "holder").write_text(f"{dead.pid}\n0\n/nowhere\nold command\n", encoding="utf-8")
    start = time.monotonic()
    result = subprocess.run(
        [str(SCRIPT), "echo", "ok"],
        env=_env(lock, CASEFILE_RUN_POLL="30"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert time.monotonic() - start < 10
    assert f"stale lock of pid {dead.pid} removed" in result.stdout
    assert "waiting for lock" not in result.stdout
    assert result.returncode == 0
    assert not lock.exists()


def test_lock_is_removed_on_term(lock: Path) -> None:
    proc = _start(lock, "sleep", "30")
    _wait_for_holder(lock)
    time.sleep(0.3)
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=15)
    assert proc.returncode == 143
    assert not lock.exists()


def test_foreign_lock_is_not_released(lock: Path) -> None:
    """Скрипт, ждавший чужой замок и убитый, чужого каталога не трогает."""
    holder = _start(lock, "sleep", "30")
    _wait_for_holder(lock)
    waiter = _start(lock, "echo", "never")
    time.sleep(0.6)
    waiter.send_signal(signal.SIGTERM)
    waiter.communicate(timeout=15)
    assert (lock / "holder").read_text(encoding="utf-8").splitlines()[0] == str(holder.pid)
    holder.send_signal(signal.SIGTERM)
    holder.communicate(timeout=15)
    assert not lock.exists()


def test_waits_for_load(lock: Path) -> None:
    proc = _start(lock, "echo", "ok", CASEFILE_RUN_MAX_LOAD="0")
    time.sleep(1)
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=15)
    assert "waiting for load " in out
    assert "< 0," in out
    assert "running:" not in out
    assert not lock.exists()
