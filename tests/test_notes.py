"""Заметки `docs/notes/` держатся тестом, а не вычиткой: состав полей и имена в тексте.

Заметки — единственное место, где знание переживает сессию агента: файлы задач
удаляются, отчёты исчезают вместе с контекстом. Правила описаны в `docs/CONVENTIONS.md`,
разделе «Заметки», но описанное прозой правило никто не исполняет: к задаче 33
шестьдесят записей из трёхсот шестнадцати остались без «Как правильно» — то есть
называли грабли и не говорили, как их обойти.

Стерегутся три разных свойства, и каждое своей проверкой:

- состав и порядок четырёх полей — именно состав, а не длина текста: «что» и «почему
  важно» пишутся сами собой, а «как правильно» требует решить, что же делать, — и
  пропускается первым;
- указатель «Где:» ведёт в существующий файл, и названный символ в этом файле есть;
- имя из кода, названное где угодно в записи, в коде проекта существует (TRK-43).
"""

import os
import re
from functools import cache
from pathlib import Path

NOTES_DIR = Path(__file__).resolve().parents[1] / "docs" / "notes"

#: Карта папки — не заметка: её `##` перечисляют файлы, а не находки.
FOLDER_MAP = "AGENTS.md"

#: Обязательные поля записи в порядке из соглашений: факт, цена, действие, место.
REQUIRED_FIELDS = ("Что", "Почему важно", "Как правильно", "Где")

#: Заголовок записи: `##` внутри файла области.
ENTRY_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)

#: Имя поля записи — жирная подпись в начале строки. Поля сверх обязательных
#: («Чем ловится») законны, поэтому состав и порядок проверяются только по своим.
FIELD_LABEL = re.compile(r"^\*\*([^:*]+):\*\*", re.MULTILINE)


def _entries() -> list[tuple[str, str, list[str]]]:
    """Все записи всех заметок: файл, заголовок, имена полей по порядку."""
    found: list[tuple[str, str, list[str]]] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        if path.name == FOLDER_MAP:
            continue
        chunks = re.split(r"^(?=## )", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for chunk in chunks:
            heading = ENTRY_HEADING.match(chunk)
            if heading is not None:
                found.append((path.name, heading.group(1), FIELD_LABEL.findall(chunk)))
    return found


def test_the_notes_are_parsed_at_all() -> None:
    """Разбор промахнулся — обе проверки ниже зеленеют на пустом множестве."""
    assert len(_entries()) > 100, "записи заметок не разобраны"


def test_every_note_names_all_four_fields() -> None:
    """Запись без «Как правильно» — рассказ о грабле, на которую наступят снова.

    Падение чинится дописыванием поля, а не правкой соседних: заметки только
    дополняются (`docs/CONVENTIONS.md`, раздел «Заметки»).
    """
    incomplete = [
        f"{file}, «{heading}»: нет полей {[f for f in REQUIRED_FIELDS if f not in labels]}"
        for file, heading, labels in _entries()
        if not set(REQUIRED_FIELDS) <= set(labels)
    ]

    assert not incomplete, incomplete


def test_every_note_keeps_the_field_order() -> None:
    """Порядок один на все заметки: инструкция раньше причины читается как каприз."""
    reordered = [
        f"{file}, «{heading}»: порядок полей {[f for f in labels if f in REQUIRED_FIELDS]}"
        for file, heading, labels in _entries()
        if [f for f in labels if f in REQUIRED_FIELDS] != list(REQUIRED_FIELDS)
    ]

    assert not reordered, reordered


# --- Указатели «Где:» ---------------------------------------------------------------

PROJECT_ROOT = NOTES_DIR.parents[1]

#: Поле «Где:» записи: от подписи до следующего поля или конца записи. Многострочное —
#: указатель на два-три места переносится по ширине строки, как и любой другой текст.
WHERE_FIELD = re.compile(r"^\*\*Где:\*\*(.*?)(?=^\*\*|\Z)", re.MULTILINE | re.DOTALL)

#: Токен в обратных кавычках: путь, имя символа или кусок команды.
QUOTED = re.compile(r"`([^`]+)`")

#: Похоже на путь в репозитории: расширение из тех, что в проекте есть, либо косая черта.
LOOKS_LIKE_PATH = re.compile(r"^[\w./-]+\.(py|md|yml|yaml|json|toml|ini|cfg|txt|sh|example)$")


def _where_pointers() -> list[tuple[str, str, str]]:
    """Все указатели «Где:» живых заметок: файл, заголовок записи, текст поля."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        if path.name == FOLDER_MAP:
            continue
        chunks = re.split(r"^(?=## )", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for chunk in chunks:
            heading = ENTRY_HEADING.match(chunk)
            field = WHERE_FIELD.search(chunk)
            if heading is not None and field is not None:
                found.append((path.name, heading.group(1), field.group(1)))
    return found


def test_every_where_pointer_leads_to_living_code() -> None:
    """Указатель «Где:» ведёт в существующий файл, а названный символ в нём находится.

    Заметку читают **до** кода и верят ей: указатель на удалённый модуль стоит
    следующему агенту получаса поисков поведения, которого нет, и заканчивается выводом
    «документация врёт» — после которого не верят уже и живым записям.

    Символы проверяются только там, где в том же указателе назван хотя бы один файл:
    «Где:» без файла (команда, папка целиком) проверять нечем, и придумывать ему правило
    хуже, чем не проверять.
    """
    problems: list[str] = []
    for name, heading, field in _where_pointers():
        files, symbols = [], []
        for token in QUOTED.findall(field):
            # `.gitignore` и подобные точечные файлы не подходят ни под расширение, ни
            # под косую черту — их выдаёт только само существование в репозитории.
            is_path = (
                LOOKS_LIKE_PATH.match(token) or "/" in token or (PROJECT_ROOT / token).exists()
            )
            (files if is_path else symbols).append(token)

        readable = []
        for token in files:
            target = PROJECT_ROOT / token
            if target.is_file():
                readable.append(target)
            elif not target.is_dir():
                problems.append(f"{name}, «{heading}»: нет файла {token}")

        if not readable:
            continue
        texts = [target.read_text(encoding="utf-8") for target in readable]
        problems += [
            f"{name}, «{heading}»: символа {symbol!r} нет в {[t.name for t in readable]}"
            for symbol in symbols
            if not any(symbol in text for text in texts)
        ]

    assert not problems, problems


# --- Имена во всём тексте записи ------------------------------------------------------

#: Папки, в которых исходников проекта нет: чужой код и кеши инструментов.
#:
#: `.venv` в этом списке не про скорость обхода, а про строгость сторожа, и с задачи 53
#: он стал обязательным. До неё окружение хоста прятал анонимный том дев-контура, и в
#: контейнере каталога не бывало вовсе; том снят, и `./:/app` приносит окружение как есть.
#: Ослабление вышло бы зелёным: проверка ищет имя из заметки **где-нибудь** в исходниках,
#: а чужой код подтверждает почти любое. Замер на настоящем окружении хоста этого проекта
#: (`virtualenv`, полный набор зависимостей с dev): имён в исходниках проекта 5245, вместе
#: с `.venv` — 165 109, то есть под 160 тысяч чужих имён, каждое из которых молча
#: подтвердило бы гнилую запись.
SKIP_DIRS = frozenset(
    {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
)

#: Идентификатор и цепочка идентификаторов через точку: `get_actor`, `LinkView.other`.
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
NAME_RUN = re.compile(rf"{IDENT}(?:\.{IDENT})*")

#: Знак, рядом с которым в тексте стоит образец, а не имя: подстановка (`normalize_*`,
#: `uq_%(table_name)s`), угловая скобка шаблона (`ck_<таблица>_author_kind`), цифра
#: (`100_percent`), дефис — приставка сортировки (`-updated_at`), флаг команды или
#: диапазон в шаблоне (`[0-9A-Za-z_]`, откуда выхватывается `z_`). Обрубок образца в коде
#: искать нечего: его там нет по форме записи, а не по гнили, и падение указывало бы не на
#: то. Цифра и дефис здесь ещё и левая граница: без них `100_percent` даёт имя `_percent`,
#: а диапазон шаблона — `z_`, и оба потом подтверждают себя случайной строкой чужого
#: файла (`docs/notes/python.md`, запись о границах в шаблоне, выхватывающем имя из текста).
CUT_MARK = frozenset("*%<>-0123456789")

#: Чем имя из кода отличается от слова прозы: подчёркивание рядом с буквой или цифрой
#: (`get_actor`) либо смена регистра внутри слова (`LinkView`). Одиночное слово —
#: `null`, `open`, `SELECT` — под это не подходит и не проверяется: отличить имя от
#: прозы там нечем, а ложное срабатывание здесь дороже пропуска.
NAME_SHAPE = re.compile(r"_[A-Za-z0-9]|[A-Za-z0-9]_|[a-z0-9][A-Z]")

#: Имя объекта базы: ограничение, индекс, ключ. Их собирает соглашение об именах
#: (`app/db/base.py`, `NAMING_CONVENTION`), и в исходниках такого имени может не быть
#: вовсе — оно живёт в схеме. Соседняя заметка про `alembic check` прямо говорит, что
#: перечислять эти имена где-либо бессмысленно: список устареет к следующей миграции.
DATABASE_OBJECT = re.compile(r"^(?:ck|fk|ix|pk|uq)_")

#: Имена из чужого кода: у записи о поведении библиотеки нет другого способа назвать то,
#: о чём она написана. Каждое проверено вручную на задачах TRK-43 и TRK-49.
OUTSIDE_NAMES = frozenset(
    {
        "get_route_handler",  # FastAPI, метод APIRoute
        "request_response",  # FastAPI, fastapi/routing.py
        "response_model_exclude_none",  # параметр маршрута FastAPI, которым не пользуемся
        "_get_flat_fields_from_params",  # внутренность разбора параметров FastAPI
        "ServerMiddleware",  # SDK MCP, промежуточный слой сервера
        "_handle_list_tools",  # SDK MCP, обработчик tools/list
        "num_nonnulls",  # функция PostgreSQL
        "pg_stat_activity",  # представление PostgreSQL
        "pg_available_extensions",  # представление PostgreSQL
        "clock_timestamp",  # функция PostgreSQL
        "statement_timestamp",  # функция PostgreSQL
        "remove_constraint",  # строка вывода `alembic check`
        "drop_constraint",  # Alembic, метод `op`
        "type_",  # Alembic, аргумент того же метода
        "MutableList",  # SQLAlchemy, обёртка изменяемого списка
        "as_mutable",  # SQLAlchemy, метод той же обёртки
        "greenlet_spawn",  # SQLAlchemy, имя из текста ошибки `MissingGreenlet`
        "exclude_none",  # pydantic, аргумент `model_dump`
        "SettingsError",  # pydantic-settings, класс ошибки из вывода
        "HandlerResult",  # SDK MCP, объявленный тип результата обработчика
        "inputSchema",  # поле протокола MCP в ответе `tools/list`
        "__anext__",  # протокол асинхронного итератора, сам язык
        "anyio_backend",  # anyio, фикстура его плагина pytest (TRK-59)
        "ScopeMismatch",  # pytest, имя из текста ошибки о масштабе фикстуры (TRK-59)
    }
)

#: Имена, которых у нас нет намеренно: снесённое, помянутое как «раньше было», и
#: варианты, названные для контраста с принятым. Освобождать имя списком, а не молча по
#: форме токена, — требование задачи TRK-43: пропуск обязан быть виден на ревизии.
RETIRED_NAMES = frozenset(
    {
        "outbox_events",  # таблица прежнего потока событий
        "stream_replay_limit",  # настройка прежнего потока событий
        "too_far_behind",  # код отказа прежнего потока событий
        "lock_journal",  # прежнее имя `lock_changes`, названо как прежнее
        "structured_filter",  # колонка снесённых сохранённых фильтров
        "question_not_found",  # кода в трекере не было: пример вранья в чужом документе
        "question_already_answered",  # там же
        "is_filterable",  # отвергнутый вариант устройства отбора
        "is_sortable",  # он же
        "aliceX",  # образец почти-совпадения у снесённой механики упоминаний
    }
)

FREED_NAMES = OUTSIDE_NAMES | RETIRED_NAMES


@cache
def _names_by_file() -> tuple[tuple[Path, frozenset[str]], ...]:
    """Идентификаторы исходников проекта, по файлам.

    Заметки в стог не входят: запись, подтверждающая сама себя, не стережёт ничего.
    Двоичное и нечитаемое пропускается молча — прочиталось текстом, значит годится.
    """
    found: list[tuple[Path, frozenset[str]]] = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        if Path(root) == NOTES_DIR:
            dirs[:] = []
            continue
        for name in files:
            path = Path(root) / name
            try:
                text = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            found.append((path, frozenset(re.findall(IDENT, text))))
    return tuple(found)


def _names_in_the_code() -> frozenset[str]:
    """Имена кода проекта — все, кроме имён этого файла.

    Свой файл исключён намеренно: в нём лежат списки имён, которых в коде нет, и разобранные
    примеры мёртвых имён. Без исключения они подтверждали бы сами себя — вернувшееся в код
    имя осталось бы освобождённым, а мёртвое имя в докстроке открывало бы его всем заметкам.
    Цена исключения: имя, объявленное только здесь, заметке цитировать нечем.
    """
    here = Path(__file__).resolve()
    return frozenset().union(*(names for path, names in _names_by_file() if path != here))


def _names_in_token(token: str) -> list[str]:
    """Имена, названные токеном, — и те, что спрятаны внутри него.

    Токен в обратных кавычках целиком именем чаще всего не является: заметка пишет вызов
    (`string_enum(TaskStatus, name="task_status")`), присваивание (`response_class=Response`),
    узел pytest, строку SQL. До TRK-49 такой токен выбрасывался целиком, и имя внутри него
    не проверял никто: `@router.get(..., response_class=EventStreamResponse)` жил в заметке
    зелёным при мёртвом классе.

    Разбор идёт по словам — токен держит и выражение, и командную строку, и узел pytest.
    Слово с косой чертой не разбирается вовсе: путь и адрес остаются вне проверки, как
    решил TRK-43, и подстановка внутри них (`{task_key}`) вместе с ними. В остальном
    берётся каждая цепочка идентификаторов через точку, не обрубленная знаком образца, и
    разбирается на звенья: заметка пишет выражение (`obj.updated_at`), которого целиком в
    коде и не бывает, а гниль сидит в звене — `IssueLinkView.issue` неверен именно классом.
    """
    names: list[str] = []
    for word in re.split(r"\s+|::", token):
        if "/" in word:
            continue
        for run in NAME_RUN.finditer(word):
            before = word[run.start() - 1] if run.start() else ""
            after = word[run.end()] if run.end() < len(word) else ""
            if before in CUT_MARK or after in CUT_MARK:
                continue
            names += [
                name
                for name in run.group(0).split(".")
                if NAME_SHAPE.search(name) and not DATABASE_OBJECT.match(name)
            ]
    return names


def _named_in_the_notes() -> list[tuple[str, str, str, str]]:
    """Имена, названные записями: файл, заголовок, токен целиком, само имя."""
    found: list[tuple[str, str, str, str]] = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        if path.name == FOLDER_MAP:
            continue
        chunks = re.split(r"^(?=## )", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for chunk in chunks:
            heading = ENTRY_HEADING.match(chunk)
            if heading is None:
                continue
            for token in QUOTED.findall(chunk):
                # Токен переносится по ширине строки, а в сообщении об ошибке его читают
                # одной строкой — переводы строк схлопываются вместе с отступом.
                shown = " ".join(token.split())
                found += [
                    (path.name, heading.group(1), shown, name) for name in _names_in_token(token)
                ]
    return found


def test_the_code_and_the_notes_are_read_for_names_at_all() -> None:
    """Промахнулся разбор — проверка ниже зеленеет на пустом множестве."""
    assert len(_names_in_the_code()) > 1000, "исходники проекта не разобраны на имена"
    assert len(_named_in_the_notes()) > 300, "имена записей не разобраны"


def test_a_name_hidden_inside_a_token_is_taken_out_of_it() -> None:
    """Разбор токена проверяется образцами, а не живыми заметками.

    Живая заметка меняется каждой задачей, и проверка на ней говорит только «сегодня
    ничего не упало». Форма токена не меняется: вызов, присваивание, перечисление через
    запятую — ради них разбор и расширен (TRK-49), а образец, который перестал разбираться,
    роняет прогон в самом узком месте.

    Живых имён образцу не требуется: разбор в код не ходит, а свой файл в стог имён не
    входит (`_names_in_the_code`) — подтвердить себя образец не может. `EventStreamResponse`
    здесь то самое мёртвое имя, которое жило зелёным внутри токена с вызовом.
    """
    assert _names_in_token("sa.Enum(TaskStatus, native_enum=False)") == [
        "TaskStatus",
        "native_enum",
    ]
    assert _names_in_token("response_class=EventStreamResponse") == [
        "response_class",
        "EventStreamResponse",
    ]
    assert _names_in_token("set_committed_value(queue, 'last_task_number', number)") == [
        "set_committed_value",
        "last_task_number",
    ]

    # Образец, а не имя: подстановка, шаблон, цифра слева — в коде такого нет по форме.
    assert _names_in_token("normalize_*") == []
    assert _names_in_token("ck_<таблица>_author_kind") == []
    assert _names_in_token("100_percent") == []
    assert _names_in_token("(?<![0-9A-Za-z_@])") == []
    # Путь и адрес не разбираются вовсе, а имя рядом с ними — разбирается.
    assert _names_in_token("tests/test_notes.py::test_every_note_keeps_the_field_order") == [
        "test_every_note_keeps_the_field_order"
    ]
    assert _names_in_token("docker compose run --rm test") == []


def test_every_name_a_note_says_is_a_name_the_code_has() -> None:
    """Имя из кода, названное где угодно в записи, обязано в коде существовать.

    Область — вся запись, а не одно поле «Где:» (TRK-43). Указатель «Где:» сверялся с
    кодом с самого начала, и разошлись не указатели: вся гниль ревизии 2026-09-09
    сидела в «Что», «Почему важно» и «Как правильно», где имя не проверял никто.
    Переименование символа ломало текст заметки молча — набор оставался зелёным, а
    следующий агент читал заметку до кода и верил ей.

    Ищется имя по всему коду проекта, а не в файлах, которые называет запись: запись
    законно поминает соседний модуль, библиотеку и SQL, и требование «имя обязано быть
    в названном файле» дало бы 55 ложных падений на 196 живых записях (TRK-43#6). Здесь
    проверяется то, что в файле не спрячешь: имени нет **нигде** — значит, его
    переименовали или не было никогда.

    Падение чинится в заметке, а не здесь: имя правится на живое, запись сносится как
    мёртвая, а законно помянутое чужое или снесённое имя вносится в `OUTSIDE_NAMES` или
    `RETIRED_NAMES` со строкой причины.
    """
    known = _names_in_the_code()
    problems = [
        f"{file}, «{heading}»: имени {name!r} нет в коде проекта"
        + (f", токен `{token}`" if token != name else "")
        for file, heading, token, name in _named_in_the_notes()
        if name not in known and name not in FREED_NAMES
    ]

    assert not problems, problems


def test_the_freed_names_are_still_absent_and_still_named() -> None:
    """Список освобождённых имён гниёт ровно так же, как заметка.

    Вернувшееся в код имя осталось бы освобождённым молча, а имя, выпавшее из всех
    записей, копит в списке мусор, который следующий уже не решится тронуть.
    """
    known = _names_in_the_code()
    named = {name for _, _, _, name in _named_in_the_notes()}
    problems = [
        f"{name}: имя вернулось в код, освобождать больше нечего"
        for name in sorted(FREED_NAMES & known)
    ]
    problems += [
        f"{name}: имени нет ни в одной записи, строка в списке лишняя"
        for name in sorted(FREED_NAMES - named)
    ]

    assert not problems, problems
