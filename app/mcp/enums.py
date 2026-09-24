"""Перечисления домена так, как их видит модель в `tools/list`.

Pydantic кладёт в схему перечисления докстроку класса. Докстроки перечислений домена —
документация разработчика на русском, и те же строки уезжают в `openapi.json` и дальше в
сгенерированный клиент интерфейса (`ui/src/shared/api/openapi.ts`). Метадата MCP при этом
английская (TRK-140#18), а править домен ради неё значило бы тащить правку через контракт
REST и клиент интерфейса.

Поэтому слой MCP объявляет свою схему каждого перечисления: `WithJsonSchema` заменяет
ссылку на `$defs` встроенной схемой со списком значений из самого перечисления и
английским описанием. Проверка значений остаётся доменной — меняется только схема.
Список значений собирается из перечисления, а не переписывается: новое значение домена
придёт в схему само.

У аргумента с собственным описанием (`Field(description=...)`) описание поля стоит в той
же встроенной схеме поверх описания перечисления — модель видит одно, более точное.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import WithJsonSchema

from app.domain.authors import AuthorKind
from app.domain.case import EntryType, RemarkOutcome, VerdictOutcome
from app.domain.links import LinkKind
from app.domain.participants import ParticipantKind
from app.domain.tasks import TaskField, TaskPriority, TaskStatus


def described(enum: type[StrEnum], description: str) -> WithJsonSchema:
    """Встроенная схема перечисления: значения домена и английское описание."""
    return WithJsonSchema(
        {"type": "string", "enum": [member.value for member in enum], "description": description}
    )


TaskStatusSchema = Annotated[TaskStatus, described(TaskStatus, "Task status")]
TaskPrioritySchema = Annotated[
    TaskPriority, described(TaskPriority, "Task priority, from lowest to highest")
]
TaskFieldSchema = Annotated[TaskField, described(TaskField, "Task field")]
EntryTypeSchema = Annotated[
    EntryType,
    described(
        EntryType,
        "Case entry type. Types up to `note` are written by agents and humans; the types "
        "after it are filed by the tracker itself with the change they record",
    ),
]
VerdictOutcomeSchema = Annotated[
    VerdictOutcome, described(VerdictOutcome, "Outcome of a review check")
]
RemarkOutcomeSchema = Annotated[
    RemarkOutcome, described(RemarkOutcome, "How a remark was resolved")
]
LinkKindSchema = Annotated[
    LinkKind,
    described(LinkKind, "Link kind, named by the role of the task the link is shown for"),
]
AuthorKindSchema = Annotated[
    AuthorKind,
    described(
        AuthorKind,
        "Kind of author. `tracker` signs the service entries the tracker files itself",
    ),
]
ParticipantKindSchema = Annotated[
    ParticipantKind,
    described(
        ParticipantKind,
        "Kind of participant. It grants no rights: participants of either kind can make "
        "any entry and any transition",
    ),
]
