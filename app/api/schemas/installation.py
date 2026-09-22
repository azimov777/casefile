"""Схемы установки: её сведения, архив для переноса и итог его приёма."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.archive import ARCHIVE_FORMAT_VERSION, ArchiveFormat


class InstallationRead(BaseModel):
    """Факты установки: одинаковы для любого запросившего и меняются только с её настройкой."""

    mcp_url: str = Field(
        examples=["http://localhost:8100/mcp"],
        description=(
            "Address an MCP client connects to, whole: scheme, host, port and path. Use it "
            "as is: it is set by the installation (`TRACKER_MCP_PUBLIC_URL`) and differs "
            "from the address of this API behind a proxy or on another machine. Unset, it "
            "is `http://localhost:<TRACKER_MCP_PORT><TRACKER_MCP_PATH>`, which is right for "
            "a client on the machine the installation runs on"
        ),
    )


class ArchiveTableRead(BaseModel):
    """Строки одной таблицы установки: значения в порядке `columns`, каждое — текстом."""

    # Модель ходит и телом приёма: поле, которого раскладка не знает, — отказ, а не
    # молча отброшенное значение.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(examples=["tasks"], description="Table name at the archive's revision")
    columns: list[str] = Field(
        examples=[["id", "key", "title"]],
        description="Column names; every row lists its values in this order",
    )
    rows: list[list[str | None]] = Field(
        examples=[[["0b9a…", "TRK-1", "First task"]]],
        description=(
            "Rows of the table. Each value is the PostgreSQL text form of the column "
            "(what `column::text` gives; time in UTC), and null is SQL NULL. The receiving "
            "Casefile hands the text back to PostgreSQL as is, so a value never passes "
            "through a JSON type"
        ),
    )


class InstallationArchive(BaseModel):
    """Архив установки: все её данные на одной ревизии схемы (`docs/moving.md`)."""

    # Модель ходит и телом приёма: поле, которого раскладка не знает, — отказ, а не
    # молча отброшенное значение.
    model_config = ConfigDict(extra="forbid")

    format: ArchiveFormat = Field(description="What the document is")
    format_version: int = Field(
        examples=[ARCHIVE_FORMAT_VERSION],
        description=(
            "Layout of this document. It changes only when the layout does; the database "
            "schema is `schema_revision`"
        ),
    )
    schema_revision: str = Field(
        examples=["7e3b52a9c1d4"],
        description=(
            "Database migration revision the rows were taken at. A Casefile that knows the "
            "revision brings the rows up to its own schema; one that does not (the archive "
            "is newer) refuses with `archive_revision_unknown`"
        ),
    )
    app_version: str = Field(examples=["0.1.0"], description="Casefile version that took it")
    exported_at: datetime = Field(description="When the archive was taken")
    tables: list[ArchiveTableRead] = Field(
        description=(
            "Every table of the installation except the migration version and idempotency "
            "keys; browser session tokens are left out of `tokens`"
        ),
    )


class InstallationArchiveUpload(BaseModel):
    """Тело приёма — ответ выгрузки как есть, вместе с оболочкой `data`."""

    # Модель ходит и телом приёма: поле, которого раскладка не знает, — отказ, а не
    # молча отброшенное значение.
    model_config = ConfigDict(extra="forbid")

    data: InstallationArchive = Field(
        description=(
            "The archive. The body is the response of `GET /api/v1/installation/archive` "
            "verbatim, so a saved download is posted back without editing"
        ),
    )


class ImportedTableRead(BaseModel):
    """Сколько строк таблицы стоит в установке после приёма."""

    name: str = Field(examples=["entries"])
    rows: int = Field(examples=[3398])


class ReplacedRowsRead(BaseModel):
    """Сколько строк приёмника заменено архивом: его люди и доступы до приёма."""

    participants: int = Field(examples=[2])
    tokens: int = Field(examples=[2])
    accounts: int = Field(examples=[1])


class ArchiveImportRead(BaseModel):
    """Итог приёма архива."""

    schema_revision: str = Field(
        examples=["c4a9d31f7e58"], description="Revision the archive was taken at"
    )
    head_revision: str = Field(
        examples=["7e3b52a9c1d4"],
        description="Revision this installation brought the data up to",
    )
    tables: list[ImportedTableRead] = Field(
        description="Rows per table in this installation after the import"
    )
    replaced: ReplacedRowsRead = Field(
        description=(
            "Rows this installation had before the import and has lost to the archive. Its "
            "own machine keys survive (`machine_keys`)"
        ),
    )
    machine_keys: list[str] = Field(
        examples=[["local-agent", "local-ui"]],
        description=(
            "Names of this installation's own keys that survived the import: the board's "
            "key and the key of this machine's agent, now attached to the archive's "
            "participants of the same name"
        ),
    )
    revoked_source_keys: int = Field(
        examples=[2],
        description=(
            "Keys of the same names that came in the archive and were revoked here: their "
            "secrets live on the machine the archive came from"
        ),
    )
