"""Инструменты по реестрам: очереди и участники.

Чтение открыто набору `task` — оно часть рабочего цикла: без списка очередей агент с
чистым контекстом не найдёт, где вообще лежат задачи, без описания очереди не знает
общего контекста её задач, без реестра участников ему некому адресовать вопрос.
Запись требует набора `main`: заводить очереди и регистрировать участников — управление
установкой, а не работа над задачей.

Выпуска токенов здесь нет и не будет: выдача доступов остаётся за человеком и идёт
только через REST (`CONCEPT.md`, 5.2).
"""

from app.domain.tokens import TokenScope
from app.mcp import views
from app.mcp.arguments import (
    CursorArg,
    IdempotencyKeyArg,
    LimitArg,
    NewParticipantNameArg,
    NewQueueKeyArg,
    ParticipantDescriptionArg,
    ParticipantKindArg,
    ParticipantNameArg,
    QueueDescriptionArg,
    QueueDescriptionChangeArg,
    QueueKeyArg,
    QueueTitleArg,
    QueueTitleChangeArg,
)
from app.mcp.idempotency import Once
from app.mcp.toolset import FILING, OVERWRITING_UPDATE, READ_ONLY, Toolset
from app.services import participants as participants_service
from app.services import queues as queues_service


def register(tools: Toolset) -> None:
    """Объявляет инструменты по реестрам: чтение — набору `task`, запись — `main`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def get_queue(key: QueueKeyArg) -> views.QueueView:
        """Returns one queue by its key: key, title and description.

        The keys of the installation's queues are listed by `list_queues`.
        """
        async with runtime.call() as (session, actor):
            return views.queue(await queues_service.read_queue(session, key, actor=actor))

    @tools.tool(annotations=READ_ONLY)
    async def list_queues(
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[views.QueueRefView]:
        """Lists the installation's queues, one page at a time: key and title. A queue's
        description is returned by `get_queue`.
        """
        async with runtime.call() as (session, actor):
            page = await queues_service.list_queues(
                session, actor=actor, limit=limit or settings.mcp_page_size, cursor=cursor
            )
            return views.page(
                (views.queue_ref(item) for item in page.items),
                next_cursor=page.next_cursor,
            )

    @tools.tool(annotations=READ_ONLY)
    async def list_participants(
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[views.ParticipantView]:
        """Lists the participant registry: humans and permanent agents, the possible
        addressees of a question. Temporary agents are not registered and are absent
        from it.
        """
        async with runtime.call() as (session, actor):
            page = await participants_service.list_participants(
                session, actor=actor, limit=limit or settings.mcp_page_size, cursor=cursor
            )
            return views.page(
                (views.participant(item) for item in page.items),
                next_cursor=page.next_cursor,
            )

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN, creating=True)
    async def create_queue(
        key: NewQueueKeyArg,
        title: QueueTitleArg,
        description: QueueDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.QueueKeyView:
        """Creates a queue with a key, a title and a description. Only a `main` token
        creates queues.
        """
        async with runtime.call() as (session, actor):

            async def create() -> views.QueueKeyView:
                return views.queue_key(
                    await queues_service.create_queue(
                        session, actor=actor, key=key, title=title, description=description
                    )
                )

            return await Once.of(create_queue, session, actor, idempotency_key).run(
                result=views.QueueKeyView,
                request={"key": key, "title": title, "description": description},
                build=create,
            )

    @tools.tool(annotations=OVERWRITING_UPDATE, scope=TokenScope.MAIN)
    async def update_queue(
        key: QueueKeyArg,
        title: QueueTitleChangeArg = None,
        description: QueueDescriptionChangeArg = None,
    ) -> views.QueueKeyView:
        """Changes a queue's title and description; a field left out stays. Only a `main`
        token edits queues. The key never changes, and the previous title and
        description are not kept.
        """
        async with runtime.call() as (session, actor):
            queue = await queues_service.get_queue(session, key)
            return views.queue_key(
                await queues_service.update_queue(
                    session, queue, actor=actor, title=title, description=description
                )
            )

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN, creating=True)
    async def register_participant(
        kind: ParticipantKindArg,
        name: NewParticipantNameArg,
        description: ParticipantDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.ParticipantNameView:
        """Registers a human or a permanent agent. Only a `main` token registers
        participants; the new participant's token is issued through the REST API. An
        existing participant's description is changed by `update_participant`.
        """
        async with runtime.call() as (session, actor):

            async def create() -> views.ParticipantNameView:
                return views.participant_name(
                    await participants_service.register_participant(
                        session, actor=actor, kind=kind, name=name, description=description
                    )
                )

            return await Once.of(register_participant, session, actor, idempotency_key).run(
                result=views.ParticipantNameView,
                request={"kind": kind, "name": name, "description": description},
                build=create,
            )

    @tools.tool(annotations=OVERWRITING_UPDATE, scope=TokenScope.MAIN)
    async def update_participant(
        name: ParticipantNameArg,
        description: ParticipantDescriptionArg,
    ) -> views.ParticipantNameView:
        """Changes a participant's description. Only a `main` token edits participants.
        Name and kind never change: the name signs entries already filed. The previous
        description is not kept.
        """
        async with runtime.call() as (session, actor):
            participant = await participants_service.get_participant(session, name)
            return views.participant_name(
                await participants_service.update_participant(
                    session, participant, actor=actor, description=description
                )
            )
