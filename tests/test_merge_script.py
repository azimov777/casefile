"""Скрипт слияния под тестом: его запускают редко и в единственный неудобный момент.

`scripts/merge-task-branch.sh` — единственное место, где проверяется результат слияния
(`docs/CONVENTIONS.md`, раздел «Слияние ветки задачи в main»). Сам он ничего из набора не
исполняет: git и docker живут на хосте, и прогнать его отсюда нечем. Но три вещи ломаются
молча и обнаруживаются ровно тогда, когда сливают ветку и меньше всего хотят разбираться
с инструментом, — их и сторожит этот файл:

- потерянный бит запуска: файл в репозитории есть, а `scripts/merge-task-branch.sh`
  отвечает «Permission denied»;
- опечатка в самом скрипте: `bash -n` ловит её здесь, а не на первом слиянии;
- разъехавшиеся скрипт и документы: строка-доказательство названа в двух документах, по
  ней же скрипт ищет непроверенные слияния, и переименование ключа в одном месте
  оставляет ревизию без единой находки — тихо и навсегда.
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
