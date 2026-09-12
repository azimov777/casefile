"""`scripts/watch-journal.sh` под тестом: временный образец сторожа (TRK-77).

Скрипт — не часть приложения: он опрашивает голым `curl` `GET /api/v1/journal` и
печатает строки в stdout, не касаясь ни базы, ни настоящего сервера. Поэтому тесты
здесь обходятся без фикстур приложения (как `tests/test_merge_script.py` обходится
без них для `scripts/merge-task-branch.sh`) — им довольно поддельного HTTP-сервера,
отвечающего тем же форматом, что и настоящий: компактный JSON без пробелов
(`separators=(",", ":")`) — свойство `JSONResponse` в Starlette
(`starlette.responses.JSONResponse.render`), а не домена проекта, и его легко упустить,
собирая тело руками в тестовом сервере, — ровно так был найден и исправлен первый
черновик этого файла: `json.dumps` без параметра вставляет пробел после `:`, разбор
`grep -o '"seq":[0-9]*'` не находит ничего, а скрипт печатает пустую строку на каждый
неудачный цикл, а не молчит.

Три вещи здесь и держатся, как и заказано в разделе «Выход» задачи:
- отбор по отслеживаемой задаче: чужая запись не попадает в вывод;
- продолжение по `seq`: вторая партия не повторяет уже увиденные записи;
- переживание отказа: остановленный сервер не роняет сторожа и не теряет записи,
  появившиеся за время простоя.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "watch-journal.sh"

#: Не настоящий секрет — просто строка, которой ищут утечку в выводе (обзорная
#: проверка 1 задачи требует `grep` по выводу и не находить в нём токен).
FAKE_TOKEN = "trk_test_token_should_never_leak"


class FakeJournal:
    """Настолько настоящий `GET /api/v1/journal`, чтобы гонять скрипт вживую.

    Поддерживает `wait`: блокирует ответ, пока не появится подходящая запись или не
    истечёт срок — тот же долгий опрос, что и у настоящего сервера
    (`docs/DEVELOPMENT.md`, «Ожидание ответа без опроса»), только на обычном `sleep`
    вместо `LISTEN/NOTIFY`. `down` изображает остановленный контейнер `api`: соединение
    рвётся, не дожидаясь ответа, — curl видит то же, что видел бы от выключенного порта.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []
        self.lock = threading.Lock()
        self.down = threading.Event()
        self.requests: list[tuple[str | None, int]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def add(self, task_key: str, title: str) -> int:
        with self.lock:
            seq = len(self.entries) + 1
            self.entries.append({"seq": seq, "task_key": task_key, "title": title})
            return seq

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _matching(self, task: str | None, after: int) -> list[dict[str, object]]:
        with self.lock:
            return [e for e in self.entries if e["task_key"] == task and e["seq"] > after]  # type: ignore[operator]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        journal = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/api/v1/journal":
                    self.send_response(404)
                    self.end_headers()
                    return
                qs = parse_qs(parsed.query)
                task = qs.get("task", [None])[0]
                after = int(qs.get("after", ["0"])[0])
                wait = float(qs.get("wait", ["0"])[0])
                assert self.headers.get("Authorization") == f"Bearer {FAKE_TOKEN}", (
                    "скрипт не прислал токен тем же заголовком, что и настоящий API"
                )
                journal.requests.append((task, after))

                deadline = time.monotonic() + wait
                matching = journal._matching(task, after)
                while not matching and time.monotonic() < deadline and not journal.down.is_set():
                    time.sleep(0.02)
                    matching = journal._matching(task, after)
                if journal.down.is_set():
                    self.connection.close()  # изображает остановленный контейнер api
                    return

                body = json.dumps(
                    {"data": matching, "meta": {"next_cursor": None, "has_more": False}},
                    separators=(",", ":"),  # тот же формат, что и Starlette (см. шапку файла)
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:  # тише вывода теста
                pass

        return Handler


class LineReader:
    """Строки stdout процесса, собираемые фоновым потоком.

    `subprocess.Popen.stdout` не отдаёт готовые строки без блокировки до конца
    процесса, а сторож — бесконечный цикл: ждать его завершения нечем.
    """

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.lines: list[str] = []
        self._proc = proc
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self.lines.append(line.rstrip("\n"))

    def wait_for(self, count: int, timeout: float) -> list[str]:
        deadline = time.monotonic() + timeout
        while len(self.lines) < count and time.monotonic() < deadline:
            time.sleep(0.05)
        return list(self.lines)


@pytest.fixture
def journal() -> Iterator[FakeJournal]:
    server = FakeJournal()
    yield server
    server.stop()


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token"
    path.write_text(FAKE_TOKEN, encoding="utf-8")
    return path


def run_watcher(
    *, url: str, token_file: Path, tasks: str, wait_seconds: int = 1, after: int = 0
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["sh", str(SCRIPT), str(after)],
        env={
            **os.environ,
            "TRACKER_URL": url,
            "TRACKER_TOKEN_FILE": str(token_file),
            "WATCH_TASKS": tasks,
            "WAIT_SECONDS": str(wait_seconds),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop_watcher(proc: subprocess.Popen[str]) -> str:
    """Останавливает сторож и отдаёт его stderr — для проверки на утечку секрета."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return proc.stderr.read() if proc.stderr else ""


def test_the_script_is_there_and_carries_the_bit_to_run_it() -> None:
    """Бит запуска — часть содержимого файла, а не свойство машины (ср. `test_merge_script.py`)."""
    assert SCRIPT.is_file(), f"нет файла {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} без бита запуска: в git он хранится как 100755"


def test_the_script_parses() -> None:
    """Опечатка обнаруживается здесь, а не при первом запуске рецепта из документа."""
    sh = shutil.which("sh")
    assert sh is not None, "в образе нет sh — проверить синтаксис нечем"
    done = subprocess.run([sh, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_it_prints_one_line_for_a_watched_task_and_none_for_another(
    journal: FakeJournal, token_file: Path
) -> None:
    """Обзорная проверка 1: отбор по отслеживаемой задаче.

    Воспроизводит ровно живую проверку из карточки: отслеживается только TRK-77, а
    запись появляется и там, и в чужой TRK-99. В выводе — одна строка на первое и ни
    одной на второе, и секрета в выводе нет.
    """
    journal.add("TRK-77", "Owner answered")
    journal.add("TRK-99", "Entry in someone else's task")

    proc = run_watcher(url=journal.url, token_file=token_file, tasks="TRK-77", wait_seconds=1)
    lines = LineReader(proc).wait_for(1, timeout=10)
    stderr = stop_watcher(proc)

    assert lines == ["1 TRK-77 Owner answered"]
    assert all("TRK-99" not in line for line in lines), "чужая задача не отслеживается вовсе"
    assert all(task != "TRK-99" for task, _after in journal.requests), (
        "сторож не должен был даже спрашивать про чужую задачу"
    )
    assert FAKE_TOKEN not in "\n".join(lines), "секрет утёк в вывод"
    assert FAKE_TOKEN not in stderr, "секрет утёк в stderr"


def test_it_resumes_by_seq_without_repeating_what_was_already_seen(
    journal: FakeJournal, token_file: Path
) -> None:
    """Обзорная проверка 4 (тесты образца): продолжение по `seq`.

    Первая запись печатается один раз; вторая, добавленная позже, добавляет ровно одну
    новую строку — курсор продолжения ушёл вперёд, а не остался на первой записи.
    """
    journal.add("TRK-77", "First")

    proc = run_watcher(url=journal.url, token_file=token_file, tasks="TRK-77", wait_seconds=1)
    reader = LineReader(proc)
    first_round = reader.wait_for(1, timeout=10)
    assert first_round == ["1 TRK-77 First"]

    journal.add("TRK-77", "Second")
    second_round = reader.wait_for(2, timeout=10)
    stop_watcher(proc)

    assert second_round == ["1 TRK-77 First", "2 TRK-77 Second"], (
        "первая запись не должна повториться, вторая обязана появиться ровно раз"
    )


def test_it_survives_an_outage_without_losing_or_repeating_entries(
    journal: FakeJournal, token_file: Path
) -> None:
    """Обзорная проверка 2: отказ установки посреди работы.

    Имитирует остановленный на время контейнер `api`: пока сервер недоступен, сторож
    жив (процесс не завершается) и не теряет позицию, а запись, появившаяся за время
    простоя, приходит ровно один раз после восстановления — без повтора уже увиденной.
    """
    journal.add("TRK-77", "Before the outage")

    proc = run_watcher(url=journal.url, token_file=token_file, tasks="TRK-77", wait_seconds=1)
    reader = LineReader(proc)
    assert reader.wait_for(1, timeout=10) == ["1 TRK-77 Before the outage"]

    journal.down.set()
    time.sleep(2.5)  # минимум один неудачный цикл (сторож пере-пробует раз в 2 с)
    assert proc.poll() is None, "сторож не должен завершаться на отказе установки"

    journal.add("TRK-77", "During the outage")
    journal.down.clear()

    lines = reader.wait_for(2, timeout=15)
    stderr = stop_watcher(proc)

    assert lines == ["1 TRK-77 Before the outage", "2 TRK-77 During the outage"], (
        "после восстановления должна появиться ровно одна новая строка, без повтора"
    )
    assert FAKE_TOKEN not in "\n".join(lines)
    assert FAKE_TOKEN not in stderr
