"""Сценарии файлов: загрузка, замена, выдача байтов, удаление, список, вложения записей.

Решение владельца TRK~8#4 (итог TRK~8#5). Ядро без входов: REST и MCP позовут эти
функции, своей логики у них не будет (TRK#216).

## Доступ — через проект

Прав на проект в ядре нет: любой участник читает и пишет любой проект (TRK#81, TRK#100).
Поэтому «доступ к файлу как к проекту» сегодня значит: каждое действие идёт через проект
файла. Архивный проект заморожен (TRK#101): загрузка, замена и удаление отказывают
`project_archived` (общая проверка `app/services/freeze.py`), чтение и выдача байтов
работают. В списке без названного проекта файлы архивных проектов скрыты (TRK#99).

## Одно хранилище, один проект у файла

Файл принадлежит ровно одному проекту. Запись дела любого проекта может прикладывать файл
любого проекта установки: ссылка — это строка `entry_files`, а не принадлежность.

## Замена и удаление

Замена кладёт новые байты под тот же идентификатор; прежние не хранятся, записи дела
показывают текущее содержимое. Удаление стирает байты и оставляет надгробие. Оба
действия, как и загрузка, не подшивают записей в дело и не пишут в ленту: кто и когда —
хранится в самом файле (отметки `files`).

## Выдача байтов ставит «когда последний раз открыт»

Единственное чтение, которое пишет. Срока жизни изображений здесь нет (отдельная задача);
отметку ставит `open_file`, и только он.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.author import created_by_columns
from app.db.models.entry import Entry
from app.db.models.file import File
from app.db.models.project import Project
from app.db.pagination import Page
from app.db.repositories import FileRepository
from app.domain.errors import FileDeletedError, FileFieldsInvalidError, TrackerFileNotFoundError
from app.domain.fields import FieldProblems
from app.domain.files import (
    FileCard,
    FileSort,
    check_file_size,
    normalize_file_ids,
    normalize_file_name,
    normalize_mime_type,
    sha256_hex,
)
from app.services import freeze
from app.services import projects as projects_service
from app.services.auth import Actor


@dataclass(frozen=True, slots=True)
class OpenedFile:
    """Выданный файл: карточка уже с отметкой открытия и байты."""

    card: FileCard
    data: bytes


@dataclass(frozen=True, slots=True)
class FilePage:
    """Страница списка файлов: карточки и курсор на следующую."""

    items: list[FileCard]
    next_cursor: str | None


# --- Чтение ---------------------------------------------------------------------------


async def read_file(session: AsyncSession, file_id: uuid.UUID, *, actor: Actor) -> FileCard:
    """Карточка файла с числом ссылающихся записей и задач; у удалённого — надгробие."""
    file = await _get(session, file_id)
    return (await _cards(session, [file]))[0]


async def list_files(
    session: AsyncSession,
    *,
    actor: Actor,
    project: str | None = None,
    query: str | None = None,
    mime_type: str | None = None,
    sort: FileSort = FileSort.ADDED,
    descending: bool = True,
    include_deleted: bool = False,
    limit: int | None = None,
    cursor: str | None = None,
) -> FilePage:
    """Файлы установки: поиск по имени, отбор по типу и проекту, сортировка, курсор.

    Отбор по типу: `image/png` — точный тип, `image` или `image/*` — всё семейство.
    Без `project` файлы архивных проектов скрыты; названный проект виден и архивным.
    Надгробия по умолчанию не показываются (`include_deleted`). Сортировка по умолчанию —
    свежие добавленные первыми; для `FileSort.OPENED` не открывавшийся файл стоит по дате
    добавления.
    """
    project_id = (
        None if project is None else (await projects_service.get_project(session, project)).id
    )
    page: Page[File] = await FileRepository(session).list_page(
        project_id=project_id,
        query=query,
        mime_type=mime_type,
        sort=sort,
        descending=descending,
        include_deleted=include_deleted,
        limit=limit,
        cursor=cursor,
    )
    return FilePage(items=await _cards(session, page.items), next_cursor=page.next_cursor)


async def open_file(session: AsyncSession, file_id: uuid.UUID, *, actor: Actor) -> OpenedFile:
    """Выдаёт байты и ставит «последний раз открыт». Удалённый файл — `file_deleted`.

    Работает и в архивном проекте: чтение заморозка не трогает.
    """
    repository = FileRepository(session)
    file = await _get(session, file_id)
    if file.deleted_at is not None:
        raise FileDeletedError(details={"id": str(file.id), "name": file.name})
    data = await repository.content(file.id)
    assert data is not None  # у живого файла строка с байтами есть всегда
    file.last_opened_at = datetime.now(UTC)
    await session.flush()
    return OpenedFile(card=(await _cards(session, [file]))[0], data=data)


# --- Изменения ------------------------------------------------------------------------


async def upload_file(
    session: AsyncSession,
    *,
    actor: Actor,
    project: str,
    name: Any,
    data: bytes,
    mime_type: Any = None,
) -> FileCard:
    """Кладёт файл в проект. Отказы: `project_archived`, `file_fields_invalid` (имя,
    тип), `file_too_large` (предел `TRACKER_FILE_MAX_BYTES`, он же в `details`)."""
    owner = await projects_service.get_project(session, project)
    await freeze.lock_unfrozen(session, project=owner)
    clean_name, clean_mime = _name_and_type(name, mime_type)
    check_file_size(len(data), get_settings().file_max_bytes)
    file = File(
        project_id=owner.id,
        name=clean_name,
        mime_type=clean_mime,
        size_bytes=len(data),
        sha256=sha256_hex(data),
        **created_by_columns(actor.author),
    )
    await FileRepository(session).add(file, data)
    return (await _cards(session, [file]))[0]


async def replace_file(
    session: AsyncSession,
    file_id: uuid.UUID,
    *,
    actor: Actor,
    data: bytes,
    name: Any = None,
    mime_type: Any = None,
) -> FileCard:
    """Заменяет содержимое под той же ссылкой; прежние байты стираются.

    Имя и тип меняются, только если их назвали. Записи дела, которые прикладывают файл,
    с этого момента показывают новое содержимое. Удалённый файл заменить нельзя
    (`file_deleted`); архивный проект — `project_archived`.
    """
    repository = FileRepository(session)
    existing = await _get(session, file_id)
    await freeze.lock_unfrozen(session, project=await _project_of(session, existing))
    file = await repository.get(file_id, for_update=True)
    assert file is not None
    if file.deleted_at is not None:
        raise FileDeletedError(details={"id": str(file.id), "name": file.name})
    if name is not None or mime_type is not None:
        new_name, new_mime = _name_and_type(
            file.name if name is None else name, file.mime_type if mime_type is None else mime_type
        )
        file.name, file.mime_type = new_name, new_mime
    check_file_size(len(data), get_settings().file_max_bytes)
    await repository.set_content(file.id, data)
    file.size_bytes = len(data)
    file.sha256 = sha256_hex(data)
    file.replaced_by_kind = actor.author.kind
    file.replaced_by_signature = actor.author.signature
    file.replaced_at = datetime.now(UTC)
    await session.flush()
    return (await _cards(session, [file]))[0]


async def delete_file(session: AsyncSession, file_id: uuid.UUID, *, actor: Actor) -> FileCard:
    """Стирает байты и оставляет надгробие: имя, тип, размер, sha256, кто и когда удалил.

    Записи, которые прикладывали файл, с этого момента показывают «файл удалён».
    Повторное удаление — `file_deleted`: надгробие уже стоит.
    """
    repository = FileRepository(session)
    existing = await _get(session, file_id)
    await freeze.lock_unfrozen(session, project=await _project_of(session, existing))
    file = await repository.get(file_id, for_update=True)
    assert file is not None
    if file.deleted_at is not None:
        raise FileDeletedError(details={"id": str(file.id), "name": file.name})
    await repository.erase_content(file.id)
    file.deleted_by_kind = actor.author.kind
    file.deleted_by_signature = actor.author.signature
    file.deleted_at = datetime.now(UTC)
    await session.flush()
    return (await _cards(session, [file]))[0]


# --- Вложения записей дела ------------------------------------------------------------


def file_ids_problem(problems: FieldProblems, value: Any) -> list[uuid.UUID]:
    """Список файлов записи из присланного значения; замечания — в накопитель, поле `files`."""
    ids: list[uuid.UUID] = []
    with problems.field("files"):
        ids = normalize_file_ids(value)
    return ids


async def require_attachable(session: AsyncSession, file_ids: Sequence[uuid.UUID]) -> None:
    """Каждый файл существует и не удалён: к записи прикладывают только живое.

    Файл любого проекта установки (итог TRK~8#5, п. 4), в том числе архивного: прикладывание
    не меняет файл, а запись подшивается в проект записи, и его заморозку проверяет подшивка.
    """
    found = await FileRepository(session).get_many(file_ids)
    for file_id in file_ids:
        file = found.get(file_id)
        if file is None:
            raise TrackerFileNotFoundError(details={"id": str(file_id)})
        if file.deleted_at is not None:
            raise FileDeletedError(details={"id": str(file.id), "name": file.name})


async def attach_files(session: AsyncSession, entry: Entry, file_ids: Sequence[uuid.UUID]) -> None:
    """Вкладывает файлы в только что созданную запись; порядок списка — порядок вложений."""
    if file_ids:
        await FileRepository(session).add_attachments(entry.id, file_ids)


async def entry_attachments(
    session: AsyncSession, entries: Sequence[Entry]
) -> dict[uuid.UUID, list[FileCard]]:
    """Вложения записей одним проходом: запись → карточки в порядке вложения.

    К каждому файлу — его текущая карточка: у живого размер, тип и sha256 нынешнего
    содержимого, у удалённого — надгробие (`FileCard.deleted`). Записи без вложений в
    результат не входят.
    """
    repository = FileRepository(session)
    by_entry = await repository.attachments([entry.id for entry in entries])
    if not by_entry:
        return {}
    all_ids = {file_id for ids in by_entry.values() for file_id in ids}
    cards = {
        card.id: card
        for card in await _cards(session, list((await repository.get_many(all_ids)).values()))
    }
    return {entry_id: [cards[file_id] for file_id in ids] for entry_id, ids in by_entry.items()}


# --- Внутреннее -----------------------------------------------------------------------


async def _get(session: AsyncSession, file_id: uuid.UUID) -> File:
    file = await FileRepository(session).get(file_id)
    if file is None:
        raise TrackerFileNotFoundError(details={"id": str(file_id)})
    return file


async def _project_of(session: AsyncSession, file: File) -> Project:
    project = await session.get(Project, file.project_id)
    assert project is not None  # внешний ключ: проект файла есть всегда
    return project


def _name_and_type(name: Any, mime_type: Any) -> tuple[str, str]:
    problems = FieldProblems()
    clean_name = clean_mime = ""
    with problems.field("name"):
        clean_name = normalize_file_name(name)
    with problems.field("mime_type"):
        clean_mime = normalize_mime_type(mime_type)
    problems.raise_as(FileFieldsInvalidError)
    return clean_name, clean_mime


async def _cards(session: AsyncSession, files: Sequence[File]) -> list[FileCard]:
    repository = FileRepository(session)
    keys = await repository.project_keys({file.project_id for file in files})
    counts = await repository.reference_counts([file.id for file in files])
    return [
        FileCard(
            id=file.id,
            project_key=keys[file.project_id],
            name=file.name,
            mime_type=file.mime_type,
            size_bytes=file.size_bytes,
            sha256=file.sha256,
            added_by=file.created_by,
            added_at=file.created_at,
            replaced_by=file.replaced_by,
            replaced_at=file.replaced_at,
            last_opened_at=file.last_opened_at,
            deleted_by=file.deleted_by,
            deleted_at=file.deleted_at,
            entries=counts.get(file.id, (0, 0))[0],
            tasks=counts.get(file.id, (0, 0))[1],
        )
        for file in files
    ]
