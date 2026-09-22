"""Установка целиком: её сведения и перенос на другую машину.

Сведения — представление над настройками процесса, одинаковое для любого токена. Архив —
все данные установки для переноса в другой Casefile (`docs/moving.md`, TRK-100): выгрузка
и приём, только администратору. Роутер переводит HTTP в вызов сценария и обратно.
"""

from fastapi import APIRouter

from app.api.deps import ActorDep, SessionDep, SettingsDep
from app.api.schemas.common import DataResponse
from app.api.schemas.installation import (
    ArchiveImportRead,
    ArchiveTableRead,
    ImportedTableRead,
    InstallationArchive,
    InstallationArchiveUpload,
    InstallationRead,
    ReplacedRowsRead,
)
from app.domain.archive import Archive, ArchiveTable
from app.services import archive as archive_service
from app.services import installation as service

router = APIRouter(prefix="/installation", tags=["installation"])


@router.get("", summary="Read the installation")
async def read_installation(
    actor: ActorDep, settings: SettingsDep
) -> DataResponse[InstallationRead]:
    """Публичный адрес MCP, из которого интерфейс собирает конфигурацию клиента агента.

    Открыт любому набору, в том числе `task`: секрета здесь нет, а экрану подключения
    агента нужен именно ключ, который у интерфейса уже есть. Ответ одинаков для любого
    токена и меняется только с настройкой установки (`TRACKER_MCP_PUBLIC_URL`), поэтому
    клиент вправе держать его всю жизнь вкладки.

    В первый экран (`GET /api/v1/bootstrap`) адрес не входит: он нужен одному экрану, а
    не первому кадру (`docs/CONCEPT.md`, 5.1).
    """
    state = service.read_installation(actor=actor, settings=settings)
    return DataResponse[InstallationRead](data=InstallationRead(mcp_url=state.mcp_url))


@router.get("/archive", summary="Export the installation")
async def export_installation(
    session: SessionDep, actor: ActorDep
) -> DataResponse[InstallationArchive]:
    """Все данные установки одним документом — чтобы поднять их в другом Casefile.

    Только администратору (`403 admin_required`): в архиве хеши паролей всех людей и
    хеши всех токенов. Ответ сохраняют как есть и отдают приёму другой установки
    (`POST` этого же адреса). Токены сеансов браузера и ключи идемпотентности не едут
    (`app/services/archive.py`).
    """
    archive = await archive_service.export_installation(session, actor=actor)
    return DataResponse[InstallationArchive](
        data=InstallationArchive(
            format=archive.format,
            format_version=archive.format_version,
            schema_revision=archive.schema_revision,
            app_version=archive.app_version,
            exported_at=archive.exported_at,
            tables=[
                ArchiveTableRead(name=table.name, columns=list(table.columns), rows=table.rows)
                for table in archive.tables
            ],
        )
    )


@router.post("/archive", summary="Import an installation archive")
async def import_installation(
    payload: InstallationArchiveUpload, session: SessionDep, actor: ActorDep
) -> DataResponse[ArchiveImportRead]:
    """Заменяет данные этой установки архивом другой — только пустой и только администратору.

    Тело — ответ выгрузки как есть. Архив более старой версии доводится миграциями до
    схемы этой установки; более новой — отказ `409 archive_revision_unknown`. Установка с
    очередями — `409 installation_not_empty`. Ключ интерфейса и ключ агента этой машины
    переживают приём, одноимённые ключи источника отзываются; сеансы браузера этой
    установки заканчиваются — войти заново учётной записью из архива.

    Не создающий маршрут (`200`, без ключа идемпотентности): повтор после успеха
    получает `installation_not_empty`, а не второй приём.
    """
    upload = payload.data
    result = await archive_service.import_installation(
        session,
        actor=actor,
        archive=Archive(
            format=upload.format,
            format_version=upload.format_version,
            schema_revision=upload.schema_revision,
            app_version=upload.app_version,
            exported_at=upload.exported_at,
            tables=tuple(
                ArchiveTable(name=table.name, columns=tuple(table.columns), rows=table.rows)
                for table in upload.tables
            ),
        ),
    )
    return DataResponse[ArchiveImportRead](
        data=ArchiveImportRead(
            schema_revision=result.schema_revision,
            head_revision=result.head_revision,
            tables=[ImportedTableRead(name=table.name, rows=table.rows) for table in result.tables],
            replaced=ReplacedRowsRead(**result.replaced),
            machine_keys=list(result.machine_keys),
            revoked_source_keys=result.revoked_source_keys,
        )
    )
