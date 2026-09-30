"""Выборки и вставки по участникам.

Репозиторий не коммитит и не откатывает: границу транзакции держит вход в приложение
(`get_session` или `session_scope`). `flush` вызывать можно и нужно — он отправляет
INSERT в базу, не фиксируя транзакцию, чтобы сценарий сразу увидел нарушение
ограничения и получил заполненные значения по умолчанию.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.pagination import Page, paginate
from app.domain.participants import ParticipantKind


class ParticipantRepository:
    """Доступ к таблице `participants`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, participant_id: uuid.UUID) -> Participant | None:
        return await self._session.get(Participant, participant_id)

    async def get_by_name(self, name: str) -> Participant | None:
        """Поиск по уже канонизированному имени: канонизацию делает домен, не запрос."""
        statement = select(Participant).where(Participant.name == name)
        return (await self._session.scalars(statement)).one_or_none()

    async def existing_names(self, names: Sequence[str]) -> set[str]:
        """Какие из перечисленных канонизированных имён есть в реестре, одним запросом.

        Нужен адресатам вопроса: их несколько, а ответ обязан назвать **все**
        несуществующие сразу — иначе агент исправляет список по одному имени за круг.
        """
        if not names:
            return set()
        statement = select(Participant.name).where(Participant.name.in_(set(names)))
        return set(await self._session.scalars(statement))

    async def list_page(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[Participant]:
        return await paginate(
            self._session, select(Participant), Participant, limit=limit, cursor=cursor
        )

    async def list_agents_open_to(self, person: Participant) -> list[Participant]:
        """Агенты, которых человек вправе взять: свои (он хозяин) и без хозяина, по имени.

        Агенты других людей сюда не входят: ключ и подключение им выдаёт только их
        хозяин или администратор (`TRK-475#14`).
        """
        statement = (
            select(Participant)
            .where(
                Participant.kind == ParticipantKind.AGENT,
                or_(Participant.owner_id == person.id, Participant.owner_id.is_(None)),
            )
            .order_by(Participant.name)
        )
        return list(await self._session.scalars(statement))

    async def add(self, participant: Participant) -> Participant:
        """Кладёт участника в сессию и отправляет INSERT, не закрывая транзакцию."""
        self._session.add(participant)
        await self._session.flush()
        return participant
