"""Короткие ответы записи в реестры: ключ проекта и имя участника без эха присланного."""

from pydantic import BaseModel

from app.db.models.participant import Participant
from app.db.models.project import Project


# Ответ `create_project`/`update_project`: только ключ, без эха названия и описания.
#
# `create_project` канонизирует регистр — это единственное, чего вызывающий не мог
# знать заранее. `update_project` ключ не меняет вовсе, но повторяет его по тому же
# правилу, что и `MutationView`: ответ должен читаться сам по себе. Название и
# описание вызывающий прислал сам; итог, если нужен, отдаёт `get_project` (TRK-144).
class ProjectKeyView(BaseModel):
    """Project key in its stored, upper-case form; the project in full is returned by
    `get_project`.
    """

    key: str


def project_key(item: Project) -> ProjectKeyView:
    """Ответ `create_project`/`update_project`: только ключ, без эха названия и описания."""
    return ProjectKeyView(key=item.key)


# Ответ `register_participant`/`update_participant`: только имя, без эха рода и описания.
#
# `register_participant` канонизирует регистр — единственное новое здесь. `name` у
# правки не меняется вовсе, но остаётся в ответе по тому же правилу, что и ключ у
# `MutationView`: ответ должен читаться сам по себе. Род и описание вызывающий
# прислал сам; реестр целиком, если нужен итог, отдаёт `list_participants` (TRK-144).
class ParticipantNameView(BaseModel):
    """Participant name in its stored, lower-case form; the registry is returned by
    `list_participants`.
    """

    name: str


def participant_name(item: Participant) -> ParticipantNameView:
    """Ответ `register_participant`/`update_participant`: только имя, без эха рода и описания."""
    return ParticipantNameView(name=item.name)
