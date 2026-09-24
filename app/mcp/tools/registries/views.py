"""Короткие ответы записи в реестры: ключ очереди и имя участника без эха присланного."""

from pydantic import BaseModel

from app.db.models.participant import Participant
from app.db.models.queue import Queue


# Ответ `create_queue`/`update_queue`: только ключ, без эха названия и описания.
#
# `create_queue` канонизирует регистр — это единственное, чего вызывающий не мог
# знать заранее. `update_queue` ключ не меняет вовсе, но повторяет его по тому же
# правилу, что и `MutationView`: ответ должен читаться сам по себе. Название и
# описание вызывающий прислал сам; итог, если нужен, отдаёт `get_queue` (TRK-144).
class QueueKeyView(BaseModel):
    """Queue key in its stored, upper-case form; the queue in full is returned by
    `get_queue`.
    """

    key: str


def queue_key(item: Queue) -> QueueKeyView:
    """Ответ `create_queue`/`update_queue`: только ключ, без эха названия и описания."""
    return QueueKeyView(key=item.key)


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
