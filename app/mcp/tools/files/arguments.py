"""Аргументы, общие для инструментов файлов: идентификатор, имя и тип."""

import uuid
from typing import Annotated

from pydantic import Field

from app.domain.errors import TrackerFileNotFoundError

FileIdArg = Annotated[
    str,
    Field(
        description=(
            "File id from `list_files` or the `files` of an entry; an unknown one is refused "
            "with `file_not_found`"
        )
    ),
]

FileNameArg = Annotated[
    str,
    Field(description="File name without a path; the name a download is saved under by default"),
]

FileNameOrNoneArg = Annotated[
    str | None, Field(description="New file name; the current one stays when not given")
]

FileMimeTypeArg = Annotated[
    str | None,
    Field(description="Media type such as `image/png`; guessed from the name when not given"),
]


def file_id(value: str) -> uuid.UUID:
    """Идентификатор файла из присланной строки; не идентификатор — тот же `file_not_found`,
    что у неизвестного: агенту важно, что такого файла нет, а не как это записано."""
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise TrackerFileNotFoundError(details={"id": value}) from error
