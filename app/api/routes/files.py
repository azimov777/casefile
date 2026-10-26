"""Файлы установки: загрузка, выдача байтов, список, замена, удаление.

Решение владельца TRK~8#4 (итог TRK~8#5). Правила файлов — в сценариях
(`app/services/files.py`): размер, имя, тип, заморозка архивного проекта, надгробие. Здесь
только транспорт: разбор `multipart/form-data`, оболочка ответа и заголовки выдачи.

Выдача байтов (`GET /files/{id}/content`) — исключение из оболочки ответа: тело — сам файл
(`ENVELOPE_EXEMPT` в `app/api/contract.py`). Токен идёт заголовком `Authorization`, как у
любого маршрута; `<img src>` его не несёт, поэтому интерфейс берёт байты запросом `fetch`
и показывает через `blob:`-адрес.
"""

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Form, Path, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.idempotency import OnceDep
from app.api.schemas.common import CollectionResponse, DataResponse
from app.api.schemas.files import (
    FileDeletion,
    FileRead,
    FileReplacement,
    FilesDeleted,
    FileUpload,
    file_read,
)
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.files import FileSort, sha256_hex
from app.services import files as service
from app.services import projects as projects_service

router = APIRouter(prefix="/files", tags=["files"])

FileIdPath = Annotated[
    uuid.UUID,
    Path(
        description="File reference (`id` of a file card)",
        examples=["0b7d4a52-6a60-4f33-8c0b-1c2f7e6f9a10"],
    ),
]
ProjectFilter = Annotated[
    str | None,
    Query(
        description=(
            "Project key. Without it files of archived projects are left out; a project "
            "named here is listed even archived"
        ),
        examples=["TRK"],
    ),
]
NameFilter = Annotated[
    str | None, Query(alias="q", description="Part of the name, ignoring case", examples=["scheme"])
]
MimeFilter = Annotated[
    str | None,
    Query(description="Type: `image/png` exactly, `image` or `image/*` for the whole family"),
]
SortQuery = Annotated[
    FileSort,
    Query(
        description=(
            "Order key: when added, when last opened (never opened counts as added), size, type"
        )
    ),
]
DescendingQuery = Annotated[
    bool, Query(description="Biggest or newest first (the default); false reverses the order")
]
UnopenedQuery = Annotated[
    bool,
    Query(
        description=(
            "True: only images with the `unopened` mark, not opened for `file_unopened_days` "
            "days (documents never). The tracker deletes nothing by itself"
        )
    ),
]
IncludeDeletedQuery = Annotated[bool, Query(description="Also list tombstones of deleted files")]


async def _read_part(session: AsyncSession, upload: UploadFile) -> bytes:
    """Байты части формы, не больше предела и одного лишнего байта.

    Лишний байт нужен, чтобы сценарий увидел превышение и отказал `file_too_large` с
    присланным размером не меньше предела плюс один; файл в память целиком не читается.
    """
    return await upload.read(await service.file_size_limit(session) + 1)


def _disposition(name: str) -> str:
    """`Content-Disposition: attachment` с именем в двух видах: ASCII и UTF-8 (RFC 6266)."""
    fallback = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


@router.post("", status_code=status.HTTP_201_CREATED, summary="Upload a file")
async def upload_file(
    form: Annotated[FileUpload, Form()],
    session: SessionDep,
    actor: ActorDep,
    once: OnceDep,
) -> DataResponse[FileRead]:
    """Кладёт файл в проект: `multipart/form-data` с полями `project`, `file` и, если имя
    не то, что у части, `name`. Тип берётся из `Content-Type` части.

    Отказы: проект неизвестен — `404 project_not_found`, архивный — `409 project_archived`,
    имя или тип не годятся — `422 file_fields_invalid`, файл больше предела установки —
    `422 file_too_large` (`details.size`, `details.max_bytes`). Повтор с тем же
    `Idempotency-Key` и тем же содержимым отвечает первой карточкой.
    """
    owner = await projects_service.get_project(session, form.project)
    data = await _read_part(session, form.file)
    given_name = form.name if form.name is not None else form.file.filename
    content_type = form.file.content_type

    async def upload() -> DataResponse[FileRead]:
        card = await service.upload_file(
            session,
            actor=actor,
            project=owner.key,
            name=given_name,
            data=data,
            mime_type=content_type,
        )
        return DataResponse[FileRead](data=file_read(card))

    return await once.run(
        DataResponse[FileRead],
        request={
            "project": owner.key,
            "name": given_name,
            "mime_type": content_type,
            "sha256": sha256_hex(data),
            "size": len(data),
        },
        build=upload,
    )


@router.get("", summary="List files of the installation")
async def list_files(
    session: SessionDep,
    actor: ActorDep,
    q: NameFilter = None,
    project: ProjectFilter = None,
    mime_type: MimeFilter = None,
    sort: SortQuery = FileSort.ADDED,
    descending: DescendingQuery = True,
    include_deleted: IncludeDeletedQuery = False,
    unopened: UnopenedQuery = False,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[FileRead]:
    """Файлы установки: поиск по имени, отбор по типу и проекту, сортировка, курсор.

    По умолчанию — свежие добавленные первыми, без надгробий. Номер страницы — только
    курсор `meta.next_cursor`; он действителен при том же отборе и порядке.
    """
    page = await service.list_files(
        session,
        actor=actor,
        project=project,
        query=q,
        mime_type=mime_type,
        sort=sort,
        descending=descending,
        include_deleted=include_deleted,
        unopened=unopened,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[FileRead].of(
        [file_read(card) for card in page.items], next_cursor=page.next_cursor
    )


@router.post("/delete", summary="Delete several files")
async def delete_files(
    payload: FileDeletion,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[FilesDeleted]:
    """Удаляет несколько файлов: выбранные (`ids`) или все под отбор (`expected_count` и
    отбор `project`, `q`, `mime_type`, `unopened` — давно не открытые изображения; без отбора —
    все файлы установки).

    Байты стираются, остаются надгробия. По отбору нужно число, которое человек
    подтвердил: не совпало с числом подходящих — `409 file_count_mismatch`
    (`details.expected`, `details.actual`), ничего не удалено. Выбранные удаляются все или
    ни одного: неизвестный файл — `404 file_not_found`, уже удалённый —
    `409 file_deleted`, архивный проект — `409 project_archived`. Повтор отвечает так же,
    как первый вызов отвечал бы на то же состояние: удалённое второй раз не удаляется.
    """
    if payload.ids is not None:
        cards = await service.delete_files(session, payload.ids, actor=actor)
    else:
        assert payload.expected_count is not None  # схема: либо `ids`, либо число
        cards = await service.delete_matching(
            session,
            actor=actor,
            expected_count=payload.expected_count,
            project=payload.project,
            query=payload.q,
            mime_type=payload.mime_type,
            unopened=bool(payload.unopened),
        )
    return DataResponse[FilesDeleted](
        data=FilesDeleted(deleted=len(cards), files=[file_read(card) for card in cards])
    )


@router.get("/{file_id}", summary="Read a file card")
async def read_file(
    file_id: FileIdPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[FileRead]:
    """Карточка файла: имя, тип, размер, `sha256`, кто и когда добавил, заменил, последний
    раз открыл, число ссылающихся записей и задач. У удалённого — надгробие
    (`deleted: true`). Неизвестный файл — `404 file_not_found`. Чтение карточки не считается
    открытием файла.
    """
    return DataResponse[FileRead](
        data=file_read(await service.read_file(session, file_id, actor=actor))
    )


@router.get(
    "/{file_id}/content",
    summary="Download the bytes of a file",
    response_class=Response,
    responses={
        200: {
            "description": "The bytes of the file, as uploaded",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def download_file(
    file_id: FileIdPath,
    session: SessionDep,
    actor: ActorDep,
) -> Response:
    """Байты файла с его `Content-Type` и `Content-Disposition: attachment`; ставит
    «последний раз открыт». Тело — сам файл, без оболочки `data`.

    Удалённый файл — `409 file_deleted`, неизвестный — `404 file_not_found`. Архивный
    проект байтов не прячет.
    """
    opened = await service.open_file(session, file_id, actor=actor)
    return Response(
        content=opened.data,
        media_type=opened.card.mime_type,
        headers={
            "Content-Disposition": _disposition(opened.card.name),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "ETag": f'"{opened.card.sha256}"',
        },
    )


@router.put("/{file_id}/content", summary="Replace the content of a file")
async def replace_file(
    file_id: FileIdPath,
    form: Annotated[FileReplacement, Form()],
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[FileRead]:
    """Кладёт новые байты под ту же ссылку; прежние стираются, истории версий нет. Записи,
    которые прикладывают файл, показывают новое содержимое.

    `multipart/form-data` с частью `file` и, если нужно переименовать, `name`. Тип берётся
    из `Content-Type` части. Удалённый файл — `409 file_deleted`, архивный проект —
    `409 project_archived`, файл больше предела — `422 file_too_large`.
    """
    data = await _read_part(session, form.file)
    card = await service.replace_file(
        session,
        file_id,
        actor=actor,
        data=data,
        name=form.name,
        mime_type=form.file.content_type,
    )
    return DataResponse[FileRead](data=file_read(card))


@router.delete("/{file_id}", summary="Delete a file")
async def delete_file(
    file_id: FileIdPath,
    session: SessionDep,
    actor: ActorDep,
) -> DataResponse[FileRead]:
    """Стирает байты и оставляет надгробие; отдаёт его. Записи, которые прикладывали файл,
    показывают «файл удалён». Повторное удаление — `409 file_deleted`, архивный проект —
    `409 project_archived`.
    """
    return DataResponse[FileRead](
        data=file_read(await service.delete_file(session, file_id, actor=actor))
    )
