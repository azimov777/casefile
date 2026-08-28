"""Триггер: родитель закрыт — что делать с открытыми подзадачами.

Это и есть то самое решение, которое задача 08 сознательно не приняла: закрывать
подзадачи вместе с родителем, запрещать закрытие или не делать ничего. Оно зависит от
команды, поэтому живёт в правиле, а не в модели связей, — и переключается параметром без
перевыкладки.

Третьего варианта — «запретить закрытие родителя» — здесь нет и быть не может: триггер
получает событие о **состоявшемся** изменении, отменять которое поздно. Запрет — это
условие перехода в воркфлоу (задача 07), и место ему там. Вместо него правило умеет
громко сказать: оставить комментарий со списком незакрытых подзадач.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.automation.context import RuleContext
from app.automation.registry import rule
from app.db.models.issue import Issue
from app.domain.automation import RuleKind
from app.domain.catalogs import StatusCategory
from app.domain.events import EventType


class Params(BaseModel):
    """Настройки правила.

    По умолчанию — `announce`: правило, приехавшее с выкладкой, не должно закрывать
    чужие задачи, даже если его включили не глядя. Массовое закрытие включают осознанно.
    """

    model_config = {"extra": "forbid"}

    mode: Literal["announce", "close"] = Field(
        default="announce",
        description="announce leaves a comment on the parent, close moves children to done",
    )
    resolution: str | None = Field(
        default=None,
        description="Resolution reference for closed children, e.g. `done` or `TRK.done`",
    )


@rule(
    key="close_children_with_parent",
    # Отображаемое название — пользовательские данные, поэтому по-русски; RUF001
    # стережёт английский в служебном слое и здесь снимается по делу.
    name="Закрытие родителя и его подзадачи",  # noqa: RUF001
    kind=RuleKind.TRIGGER,
    events=(EventType.ISSUE_STATUS_CHANGED,),
    params=Params,
    description=(
        "When a parent issue moves to a done status, either close its open subtasks "
        "or leave a comment listing them"
    ),
)
async def close_children_with_parent(ctx: RuleContext) -> None:
    """Родитель уехал в категорию `done` — разобраться с его подзадачами."""
    params = ctx.params
    assert isinstance(params, Params)

    parent = ctx.target
    if parent.status.category is not StatusCategory.DONE:
        # Смена статуса внутри работы подзадач не касается. Категория, а не ключ:
        # команда вправе назвать закрывающий статус как угодно.
        ctx.skip("parent_not_done")

    children = await ctx.children()
    open_children = [item for item in children if item.status.category is not StatusCategory.DONE]
    if not open_children:
        return

    if params.mode == "announce":
        await ctx.comment(_announcement(open_children), issue=parent)
        return

    stuck: list[Issue] = []
    for child in open_children:
        moved = await ctx.transition_to_category(
            StatusCategory.DONE,
            issue=child,
            resolution=params.resolution,
        )
        if moved is None:
            # Перехода в закрывающий статус в графе процесса подзадачи нет — или он есть,
            # но требует полей, которых нет. Обходить воркфлоу правилу нельзя, поэтому
            # такая подзадача остаётся открытой и попадает в комментарий: молчаливый
            # пропуск оставил бы человека в уверенности, что закрыто всё.
            stuck.append(child)

    if stuck:
        await ctx.comment(_stuck_notice(stuck), issue=parent)


def _announcement(children: list[Issue]) -> str:
    listed = ", ".join(item.key for item in children)
    return f"Задача закрыта, но подзадачи ещё открыты: {listed}"


def _stuck_notice(children: list[Issue]) -> str:
    listed = ", ".join(item.key for item in children)
    return (
        "Подзадачи не удалось закрыть — в их процессе нет доступного перехода "
        f"в завершающий статус: {listed}"
    )
