"""Атрибуты проекта (TRK-157): одно действие «задать значение», снятие с причиной,
история записями дела проекта, оба интерфейса.

Правила — `CONCEPT.md`, 3.2 («Атрибуты») и 3.4 («Дело проекта»): имя уникально без учёта
регистра, значение не длиннее 1 000 знаков, причина обязательна при изменении и снятии и
необязательна при заведении; тип записи (`attribute_created`, `attribute_changed`,
`attribute_removed`) выбирает трекер.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entry import Entry
from app.db.models.project import Project
from app.db.repositories import EntryRepository
from app.domain.attributes import MAX_ATTRIBUTE_VALUE_LENGTH
from app.domain.case import SERVICE_ENTRY_TYPES, AttributeFacts, EntryType
from app.domain.errors import (
    AttributeNotFoundError,
    AttributeReasonRequiredError,
    AttributeValueTooLongError,
    EntryFieldsInvalidError,
    InvalidAttributeNameError,
)
from app.services import attributes as service
from app.services import case as case_service
from app.services.auth import Actor
from conftest import Connect, call, refuse

ATTRIBUTES = "/api/v1/projects/{key}/attributes/{name}"
ATTRIBUTE_TYPES = (
    EntryType.ATTRIBUTE_CREATED,
    EntryType.ATTRIBUTE_CHANGED,
    EntryType.ATTRIBUTE_REMOVED,
)


async def _history(session: AsyncSession, project: Project, name: str) -> list[Entry]:
    """История одного атрибута: записи дела проекта трёх типов, отобранные по имени.

    Отбор по имени без учёта регистра — так же, как трекер сравнивает имена: история не
    распадается на написания.
    """
    page = await EntryRepository(session).list_project_page(
        project.id, types=list(ATTRIBUTE_TYPES), limit=100
    )
    return [entry for entry in page.items if entry.payload["name"].lower() == name.lower()]


# --- Сценарий: заведение, изменение, снятие -------------------------------------------


async def test_creating_an_attribute_needs_no_reason(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Обзорная проверка 1: заведение без причины проходит и подшивает `attribute_created`."""
    result = await service.set_attribute(
        db_session, project, actor=task_actor, name="repoURL", value="github.com/x/y"
    )

    assert (result.attribute.name, result.attribute.value) == ("repoURL", "github.com/x/y")
    assert result.entry is not None
    assert result.entry.type is EntryType.ATTRIBUTE_CREATED
    assert result.entry.title == "Attribute created: repoURL"
    assert result.entry.payload == {"name": "repoURL", "after": "github.com/x/y", "reason": None}
    assert (result.entry.project_id, result.entry.task_id) == (project.id, None)


async def test_a_reason_given_at_creation_is_kept(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    result = await service.set_attribute(
        db_session, project, actor=task_actor, name="branch", value="main", reason="  Так в git  "
    )

    assert result.entry is not None
    assert result.entry.payload["reason"] == "Так в git"


@pytest.mark.parametrize("reason", [None, "", "   "])
async def test_changing_without_a_reason_is_refused(
    db_session: AsyncSession, project: Project, task_actor: Actor, reason: str | None
) -> None:
    """Обзорная проверка 1: изменение без причины — `attribute_reason_required`."""
    await service.set_attribute(db_session, project, actor=task_actor, name="branch", value="main")

    with pytest.raises(AttributeReasonRequiredError) as refused:
        await service.set_attribute(
            db_session, project, actor=task_actor, name="branch", value="trunk", reason=reason
        )

    assert refused.value.details == {"name": "branch", "action": "change"}
    [attribute] = await service.list_attributes(db_session, project, actor=task_actor)
    assert attribute.value == "main"


async def test_changing_with_a_reason_files_before_and_after(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    await service.set_attribute(db_session, project, actor=task_actor, name="branch", value="main")
    result = await service.set_attribute(
        db_session, project, actor=task_actor, name="branch", value="trunk", reason="Переехали"
    )

    assert result.entry is not None
    assert result.entry.type is EntryType.ATTRIBUTE_CHANGED
    assert result.entry.payload == {
        "name": "branch",
        "before": "main",
        "after": "trunk",
        "reason": "Переехали",
    }


async def test_the_same_value_changes_nothing_and_needs_no_reason(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    await service.set_attribute(db_session, project, actor=task_actor, name="branch", value="main")
    before = len(await _history(db_session, project, "branch"))

    result = await service.set_attribute(
        db_session, project, actor=task_actor, name="BRANCH", value="main"
    )

    assert result.entry is None
    assert len(await _history(db_session, project, "branch")) == before


async def test_a_name_in_another_case_is_the_same_attribute(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Обзорная проверка 1: другой регистр — тот же атрибут; хранимое имя не меняется."""
    await service.set_attribute(db_session, project, actor=task_actor, name="RepoURL", value="a")
    changed = await service.set_attribute(
        db_session, project, actor=task_actor, name="repourl", value="b", reason="Переезд"
    )

    assert changed.entry is not None
    assert changed.entry.type is EntryType.ATTRIBUTE_CHANGED
    assert changed.entry.payload["name"] == "RepoURL"
    attributes = await service.list_attributes(db_session, project, actor=task_actor)
    assert [(item.name, item.value) for item in attributes] == [("RepoURL", "b")]


async def test_a_value_over_the_limit_is_refused(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Обзорная проверка 1: знаков, а не байтов — кириллица в пределе проходит."""
    at_limit = "ж" * MAX_ATTRIBUTE_VALUE_LENGTH
    accepted = await service.set_attribute(
        db_session, project, actor=task_actor, name="note", value=at_limit
    )
    assert accepted.attribute.value == at_limit

    with pytest.raises(AttributeValueTooLongError) as refused:
        await service.set_attribute(
            db_session,
            project,
            actor=task_actor,
            name="other",
            value="ж" * (MAX_ATTRIBUTE_VALUE_LENGTH + 1),
        )

    assert refused.value.details == {
        "length": MAX_ATTRIBUTE_VALUE_LENGTH + 1,
        "max_length": MAX_ATTRIBUTE_VALUE_LENGTH,
    }


@pytest.mark.parametrize("name", ["", "has space", "точка", "a.b", "x" * 65, "a/b"])
async def test_an_invalid_name_is_refused(
    db_session: AsyncSession, project: Project, task_actor: Actor, name: str
) -> None:
    with pytest.raises(InvalidAttributeNameError):
        await service.set_attribute(db_session, project, actor=task_actor, name=name, value="v")


async def test_the_value_is_stored_as_sent(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    result = await service.set_attribute(
        db_session, project, actor=task_actor, name="cmd", value="  make test\n"
    )

    assert result.attribute.value == "  make test\n"


async def test_removing_files_the_last_value_and_the_reason(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    await service.set_attribute(db_session, project, actor=task_actor, name="Branch", value="main")

    entry = await service.remove_attribute(
        db_session, project, actor=task_actor, name="branch", reason="Ветка не нужна"
    )

    assert entry.type is EntryType.ATTRIBUTE_REMOVED
    assert entry.title == "Attribute removed: Branch"
    assert entry.payload == {"name": "Branch", "before": "main", "reason": "Ветка не нужна"}
    assert await service.list_attributes(db_session, project, actor=task_actor) == []


@pytest.mark.parametrize("reason", [None, "", "  "])
async def test_removing_without_a_reason_is_refused(
    db_session: AsyncSession, project: Project, task_actor: Actor, reason: str | None
) -> None:
    """Обзорная проверка 1: снятие без причины — `attribute_reason_required`."""
    await service.set_attribute(db_session, project, actor=task_actor, name="branch", value="main")

    with pytest.raises(AttributeReasonRequiredError):
        await service.remove_attribute(
            db_session, project, actor=task_actor, name="branch", reason=reason
        )

    assert len(await service.list_attributes(db_session, project, actor=task_actor)) == 1


async def test_removing_a_missing_attribute_is_not_found(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Обзорная проверка 1: снятие несуществующего — `attribute_not_found`, даже без причины."""
    with pytest.raises(AttributeNotFoundError) as refused:
        await service.remove_attribute(
            db_session, project, actor=task_actor, name="nothing", reason=None
        )

    assert refused.value.details == {"key": "TRK", "name": "nothing"}


async def test_a_removed_attribute_is_created_anew(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    await service.set_attribute(db_session, project, actor=task_actor, name="branch", value="main")
    await service.remove_attribute(
        db_session, project, actor=task_actor, name="branch", reason="Снята"
    )

    again = await service.set_attribute(
        db_session, project, actor=task_actor, name="Branch", value="dev"
    )

    assert again.entry is not None
    assert again.entry.type is EntryType.ATTRIBUTE_CREATED
    assert again.attribute.name == "Branch"


# --- История --------------------------------------------------------------------------


async def test_one_attribute_history_is_rebuilt_from_the_case_by_name(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Обзорная проверка 2: каждое заведение, изменение и снятие — запись с `name`,
    значениями и `reason`; отбор записей по имени восстанавливает историю атрибута."""
    await service.set_attribute(db_session, project, actor=task_actor, name="repo", value="a")
    await service.set_attribute(db_session, project, actor=task_actor, name="branch", value="main")
    await service.set_attribute(
        db_session, project, actor=task_actor, name="REPO", value="b", reason="Переезд"
    )
    await service.remove_attribute(
        db_session, project, actor=task_actor, name="repo", reason="Архив"
    )
    await service.set_attribute(
        db_session, project, actor=task_actor, name="Repo", value="c", reason="Вернули"
    )

    history = await _history(db_session, project, "repo")

    assert [(entry.type, entry.payload) for entry in history] == [
        (EntryType.ATTRIBUTE_CREATED, {"name": "repo", "after": "a", "reason": None}),
        (
            EntryType.ATTRIBUTE_CHANGED,
            {"name": "repo", "before": "a", "after": "b", "reason": "Переезд"},
        ),
        (EntryType.ATTRIBUTE_REMOVED, {"name": "repo", "before": "b", "reason": "Архив"}),
        (EntryType.ATTRIBUTE_CREATED, {"name": "Repo", "after": "c", "reason": "Вернули"}),
    ]
    # Номера идут по порядку в деле проекта, после `created` проекта.
    nos = [entry.no for entry in history]
    assert nos == sorted(nos)


async def test_attribute_entries_are_service_entries_with_the_name_in_the_index(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    await service.set_attribute(db_session, project, actor=task_actor, name="repo", value="a")

    index = await case_service.project_case_index(db_session, project, actor=task_actor)

    assert set(ATTRIBUTE_TYPES) <= SERVICE_ENTRY_TYPES
    assert index[-1].facts == AttributeFacts(type=EntryType.ATTRIBUTE_CREATED, name="repo")


async def test_an_agent_cannot_file_an_attribute_entry_directly(
    db_session: AsyncSession, project: Project, task_actor: Actor
) -> None:
    """Служебный тип подшивает только сценарий: в деле проекта его не принять руками."""
    with pytest.raises(EntryFieldsInvalidError):
        await case_service.append_project_entry(
            db_session, project, actor=task_actor, type="attribute_created", title="Руками"
        )


# --- REST -----------------------------------------------------------------------------


@pytest.fixture
async def task_client(client: AsyncClient, task_secret: str) -> AsyncClient:
    """Клиент с токеном набора `task`: атрибуты — рабочий цикл, а не управление."""
    client.headers["Authorization"] = f"Bearer {task_secret}"
    return client


async def test_rest_sets_changes_and_removes_with_a_task_token(
    task_client: AsyncClient, project: Project
) -> None:
    """Обзорная проверка 3: токен `task` ставит и снимает; карточка — актуальные значения."""
    created = await task_client.put(
        ATTRIBUTES.format(key="trk", name="Repo"), json={"value": "github.com/a"}
    )
    assert created.status_code == 200, created.text
    assert {k: created.json()["data"][k] for k in ("name", "value")} == {
        "name": "Repo",
        "value": "github.com/a",
    }

    await task_client.put(ATTRIBUTES.format(key="TRK", name="branch"), json={"value": "main"})
    changed = await task_client.put(
        ATTRIBUTES.format(key="TRK", name="repo"),
        json={"value": "github.com/b", "reason": "Переезд"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["name"] == "Repo"

    removed = await task_client.post(
        ATTRIBUTES.format(key="TRK", name="BRANCH") + "/remove", json={"reason": "Лишний"}
    )
    assert removed.status_code == 200, removed.text
    entry = removed.json()["data"]
    assert (entry["type"], entry["task_key"], entry["project_key"]) == (
        "attribute_removed",
        None,
        "TRK",
    )
    assert entry["payload"] == {"name": "branch", "before": "main", "reason": "Лишний"}

    card = await task_client.get("/api/v1/projects/TRK")
    assert card.status_code == 200
    assert [(a["name"], a["value"]) for a in card.json()["data"]["attributes"]] == [
        ("Repo", "github.com/b")
    ]

    case = await task_client.get(
        "/api/v1/projects/TRK/entries",
        params={"types": ["attribute_created", "attribute_changed", "attribute_removed"]},
    )
    assert [(item["type"], item["payload"]["name"]) for item in case.json()["data"]] == [
        ("attribute_created", "Repo"),
        ("attribute_created", "branch"),
        ("attribute_changed", "Repo"),
        ("attribute_removed", "branch"),
    ]


@pytest.mark.parametrize(
    ("method", "suffix", "body", "status", "code"),
    [
        (
            "put",
            "",
            {"value": "x" * (MAX_ATTRIBUTE_VALUE_LENGTH + 1)},
            422,
            "attribute_value_too_long",
        ),
        ("put", "", {"value": "trunk"}, 422, "attribute_reason_required"),
        ("post", "/remove", {"reason": " "}, 422, "attribute_reason_required"),
    ],
)
async def test_rest_refusals_carry_their_codes(
    task_client: AsyncClient,
    project: Project,
    method: str,
    suffix: str,
    body: dict[str, Any],
    status: int,
    code: str,
) -> None:
    await task_client.put(ATTRIBUTES.format(key="TRK", name="branch"), json={"value": "main"})

    response = await getattr(task_client, method)(
        ATTRIBUTES.format(key="TRK", name="branch") + suffix, json=body
    )

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


async def test_rest_refuses_a_missing_attribute_and_an_invalid_name(
    task_client: AsyncClient, project: Project
) -> None:
    missing = await task_client.post(
        ATTRIBUTES.format(key="TRK", name="nothing") + "/remove", json={"reason": "Нет"}
    )
    invalid = await task_client.put(ATTRIBUTES.format(key="TRK", name="a.b"), json={"value": "v"})

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "attribute_not_found"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_attribute_name"


async def test_rest_repeats_a_set_by_its_idempotency_key(
    task_client: AsyncClient, project: Project
) -> None:
    """Повтор с ключом не применяет значение второй раз поверх чужой правки."""
    headers = {"Idempotency-Key": "c0ffee00-0000-4000-8000-000000000157"}
    first = await task_client.put(
        ATTRIBUTES.format(key="TRK", name="branch"), json={"value": "main"}, headers=headers
    )
    await task_client.put(
        ATTRIBUTES.format(key="TRK", name="branch"), json={"value": "dev", "reason": "Сменили"}
    )
    repeated = await task_client.put(
        ATTRIBUTES.format(key="TRK", name="BRANCH"), json={"value": "main"}, headers=headers
    )

    assert first.json() == repeated.json()
    card = await task_client.get("/api/v1/projects/TRK")
    assert [a["value"] for a in card.json()["data"]["attributes"]] == ["dev"]


# --- MCP ------------------------------------------------------------------------------


async def test_mcp_sets_and_removes_with_a_task_token(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    """Обзорная проверка 3: `get_project` отдаёт актуальные значения после серии изменений."""
    async with mcp_session(task_secret) as session:
        created = await call(session, "set_attribute", key="trk", name="Repo", value="a")
        same = await call(session, "set_attribute", key="TRK", name="repo", value="a")
        changed = await call(
            session, "set_attribute", key="TRK", name="REPO", value="b", reason="Переезд"
        )
        await call(session, "set_attribute", key="TRK", name="branch", value="main")
        removed = await call(session, "remove_attribute", key="TRK", name="Branch", reason="Лишний")
        card = await call(session, "get_project", key="TRK")
        bodies = await call(session, "read_project_entries", key="TRK", nos=[removed["no"]])

    assert created == {"project_key": "TRK", "name": "Repo", "value": "a", "no": 2}
    assert same["no"] is None
    assert (changed["name"], changed["value"], changed["no"]) == ("Repo", "b", 3)
    assert removed == {"project_key": "TRK", "name": "branch", "no": 5}
    assert card["attributes"] == [{"name": "Repo", "value": "b"}]
    assert [(line["type"], line["facts"]) for line in card["index"][1:]] == [
        ("attribute_created", {"type": "attribute_created", "name": "Repo"}),
        ("attribute_changed", {"type": "attribute_changed", "name": "Repo"}),
        ("attribute_created", {"type": "attribute_created", "name": "branch"}),
        ("attribute_removed", {"type": "attribute_removed", "name": "branch"}),
    ]
    [entry] = bodies["items"]
    assert entry["payload"] == {"name": "branch", "before": "main", "reason": "Лишний"}


async def test_mcp_refusals_name_their_codes(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        await call(session, "set_attribute", key="TRK", name="branch", value="main")
        no_reason = await refuse(session, "set_attribute", key="TRK", name="branch", value="dev")
        too_long = await refuse(
            session,
            "set_attribute",
            key="TRK",
            name="other",
            value="x" * (MAX_ATTRIBUTE_VALUE_LENGTH + 1),
        )
        missing = await refuse(session, "remove_attribute", key="TRK", name="nothing", reason="Нет")
        blank = await refuse(session, "remove_attribute", key="TRK", name="branch", reason=" ")

    assert "attribute_reason_required" in no_reason
    assert "attribute_value_too_long" in too_long
    assert "attribute_not_found" in missing
    assert "attribute_reason_required" in blank


async def test_mcp_removal_repeats_by_its_idempotency_key(
    mcp_session: Connect, task_secret: str, project: Project
) -> None:
    async with mcp_session(task_secret) as session:
        await call(session, "set_attribute", key="TRK", name="branch", value="main")
        arguments = {
            "key": "TRK",
            "name": "branch",
            "reason": "Лишний",
            "idempotency_key": "c0ffee00-0000-4000-8000-000000000158",
        }
        first = await call(session, "remove_attribute", **arguments)
        second = await call(session, "remove_attribute", **arguments)

    assert first == second


async def test_both_attribute_tools_are_in_the_task_set(
    mcp_session: Connect, task_secret: str
) -> None:
    async with mcp_session(task_secret) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}

    assert {"set_attribute", "remove_attribute"} <= names
