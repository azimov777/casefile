"""Выборки и сохранение графов воркфлоу; бизнес-инварианты проверяет сервис."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.catalog import Status
from app.db.models.issue import Issue
from app.db.models.queue import QueueIssueType
from app.db.models.workflow import Transition, Workflow, WorkflowStatus


class WorkflowRepository:
    """Доступ к воркфлоу, переходам и их использованию задачами."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, workflow_id: uuid.UUID) -> Workflow | None:
        statement = select(Workflow).where(Workflow.id == workflow_id)
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def get_by_name(self, queue_id: uuid.UUID, name: str) -> Workflow | None:
        statement = select(Workflow).where(
            Workflow.queue_id == queue_id,
            Workflow.name == name,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def list_for_queue(self, queue_id: uuid.UUID) -> list[Workflow]:
        statement = (
            select(Workflow)
            .where(Workflow.queue_id == queue_id)
            .order_by(Workflow.created_at, Workflow.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def get_for_issue_type(
        self,
        queue_id: uuid.UUID,
        issue_type_id: uuid.UUID,
    ) -> Workflow | None:
        statement = (
            select(Workflow)
            .join(QueueIssueType, QueueIssueType.workflow_id == Workflow.id)
            .where(
                QueueIssueType.queue_id == queue_id,
                QueueIssueType.issue_type_id == issue_type_id,
            )
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def add(self, workflow: Workflow) -> Workflow:
        self._session.add(workflow)
        await self._session.flush()
        return workflow

    async def replace_graph(
        self,
        workflow: Workflow,
        *,
        initial_status: Status,
        status_links: Sequence[WorkflowStatus],
        transitions: Sequence[Transition],
    ) -> Workflow:
        """Заменяет граф целиком после того, как сервис проверил будущую форму.

        Коллекции меняются через ORM, чтобы загруженный объект немедленно отражал
        результат и API не прочитал старые связи после массового SQL-удаления.
        """
        # Сначала удалить старые рёбра и членства: если новое ребро занимает ту же
        # уникальную пару, INSERT до DELETE упал бы на ограничении, хотя итоговый граф
        # корректен. Это промежуточный flush внутри той же транзакции, не коммит.
        workflow.transitions = []
        workflow.status_links = []
        await self._session.flush()

        workflow.initial_status = initial_status
        workflow.status_links = list(status_links)
        workflow.transitions = list(transitions)
        await self._session.flush()
        return workflow

    async def delete(self, workflow: Workflow) -> None:
        await self._session.delete(workflow)
        await self._session.flush()

    async def get_transition(
        self,
        workflow_id: uuid.UUID,
        transition_id: uuid.UUID,
    ) -> Transition | None:
        statement = select(Transition).where(
            Transition.workflow_id == workflow_id,
            Transition.id == transition_id,
        )
        return (await self._session.scalars(statement)).unique().one_or_none()

    async def assigned_issue_types(self, workflow_id: uuid.UUID) -> list[QueueIssueType]:
        statement = (
            select(QueueIssueType)
            .where(QueueIssueType.workflow_id == workflow_id)
            .order_by(QueueIssueType.created_at, QueueIssueType.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def queue_assignments(self, queue_id: uuid.UUID) -> list[QueueIssueType]:
        statement = (
            select(QueueIssueType)
            .where(QueueIssueType.queue_id == queue_id)
            .order_by(QueueIssueType.created_at, QueueIssueType.id)
        )
        return list((await self._session.scalars(statement)).unique())

    async def assignments_for_issues_in_status(
        self,
        status_id: uuid.UUID,
        *,
        queue_id: uuid.UUID | None = None,
    ) -> list[QueueIssueType]:
        """Процессы типов задач, затронутых административным переносом статуса."""
        statement = (
            select(QueueIssueType)
            .join(
                Issue,
                (Issue.queue_id == QueueIssueType.queue_id)
                & (Issue.issue_type_id == QueueIssueType.issue_type_id),
            )
            .where(Issue.status_id == status_id)
            .distinct()
        )
        if queue_id is not None:
            statement = statement.where(Issue.queue_id == queue_id)
        return list((await self._session.scalars(statement)).unique())

    async def count_assignments(self, workflow_id: uuid.UUID) -> int:
        statement = (
            select(func.count())
            .select_from(QueueIssueType)
            .where(QueueIssueType.workflow_id == workflow_id)
        )
        return (await self._session.scalar(statement)) or 0

    async def count_status_usage(self, status_id: uuid.UUID) -> int:
        """Сколько графов содержит статус: удаление справочника иначе порвало бы их."""
        statement = (
            select(func.count())
            .select_from(WorkflowStatus)
            .where(WorkflowStatus.status_id == status_id)
        )
        return (await self._session.scalar(statement)) or 0

    async def count_required_field_usage(self, field_ref: str) -> int:
        """Сколько переходов требуют поле: скрытие иначе оставило бы вечную блокировку."""
        statement = (
            select(func.count())
            .select_from(Transition)
            .where(Transition.required_fields.contains([field_ref]))
        )
        return (await self._session.scalar(statement)) or 0

    async def assignments_requiring_field(self, field_ref: str) -> list[QueueIssueType]:
        statement = (
            select(QueueIssueType)
            .join(Transition, Transition.workflow_id == QueueIssueType.workflow_id)
            .where(Transition.required_fields.contains([field_ref]))
            .distinct()
        )
        return list((await self._session.scalars(statement)).unique())

    async def issue_counts_by_status(self, workflow_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Распределение живых задач назначенного процесса по статусам."""
        statement = (
            select(Issue.status_id, func.count())
            .join(
                QueueIssueType,
                (QueueIssueType.queue_id == Issue.queue_id)
                & (QueueIssueType.issue_type_id == Issue.issue_type_id),
            )
            .where(QueueIssueType.workflow_id == workflow_id)
            .group_by(Issue.status_id)
        )
        result = await self._session.execute(statement)
        return dict(result.all())

    async def count_issues_for_status(
        self,
        workflow_id: uuid.UUID,
        status_id: uuid.UUID,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(Issue)
            .join(
                QueueIssueType,
                (QueueIssueType.queue_id == Issue.queue_id)
                & (QueueIssueType.issue_type_id == Issue.issue_type_id),
            )
            .where(
                QueueIssueType.workflow_id == workflow_id,
                Issue.status_id == status_id,
            )
        )
        return (await self._session.scalar(statement)) or 0

    async def count_issues_outside_statuses(
        self,
        *,
        queue_id: uuid.UUID,
        issue_type_id: uuid.UUID,
        status_ids: set[uuid.UUID],
    ) -> int:
        statement = (
            select(func.count())
            .select_from(Issue)
            .where(
                Issue.queue_id == queue_id,
                Issue.issue_type_id == issue_type_id,
            )
        )
        if status_ids:
            statement = statement.where(Issue.status_id.not_in(status_ids))
        return (await self._session.scalar(statement)) or 0
