"""Чистые инварианты графа воркфлоу: без базы и транспорта."""

import pytest

from app.domain.catalogs import StatusCategory
from app.domain.errors import InvalidWorkflowGraphError
from app.domain.workflows import (
    TransitionDefinition,
    WorkflowGraphDefinition,
    WorkflowStatusDefinition,
    missing_required_fields,
    validate_graph,
)


def _status(ref: str, category: StatusCategory) -> WorkflowStatusDefinition:
    return WorkflowStatusDefinition(ref=ref, category=category)


def _transition(
    source: str | None,
    target: str,
    *,
    name: str | None = None,
    resolution: bool = False,
) -> TransitionDefinition:
    return TransitionDefinition(
        name=name or f"{source or 'any'} to {target}",
        source_status=source,
        target_status=target,
        requires_resolution=resolution,
    )


def _valid_graph() -> WorkflowGraphDefinition:
    return WorkflowGraphDefinition(
        initial_status="open",
        statuses=(
            _status("open", StatusCategory.NEW),
            _status("work", StatusCategory.IN_PROGRESS),
            _status("closed", StatusCategory.DONE),
        ),
        transitions=(
            _transition("open", "work"),
            _transition("work", "closed", resolution=True),
            _transition("closed", "open"),
        ),
    )


def test_valid_graph_reaches_done_and_can_reopen() -> None:
    validate_graph(_valid_graph())


@pytest.mark.parametrize(
    ("graph", "reason"),
    [
        (
            WorkflowGraphDefinition(
                initial_status="missing",
                statuses=_valid_graph().statuses,
                transitions=_valid_graph().transitions,
            ),
            "initial_status_missing",
        ),
        (
            WorkflowGraphDefinition(
                initial_status="open",
                statuses=_valid_graph().statuses,
                transitions=(
                    _transition("open", "closed", resolution=True),
                    _transition("closed", "open"),
                ),
            ),
            "unreachable_status",
        ),
        (
            WorkflowGraphDefinition(
                initial_status="open",
                statuses=_valid_graph().statuses,
                transitions=(
                    _transition("open", "work"),
                    _transition("closed", "open"),
                ),
            ),
            "dead_end",
        ),
        (
            WorkflowGraphDefinition(
                initial_status="open",
                statuses=_valid_graph().statuses,
                transitions=(
                    _transition("open", "work"),
                    _transition("work", "open"),
                    _transition("closed", "open"),
                ),
            ),
            "no_path_to_done",
        ),
        (
            WorkflowGraphDefinition(
                initial_status="open",
                statuses=_valid_graph().statuses,
                transitions=(
                    _transition("open", "work"),
                    _transition("work", "closed"),
                ),
            ),
            "done_transition_requires_resolution",
        ),
    ],
)
def test_invalid_graph_reports_the_concrete_problem(
    graph: WorkflowGraphDefinition,
    reason: str,
) -> None:
    with pytest.raises(InvalidWorkflowGraphError) as error:
        validate_graph(graph)

    assert reason in {problem["reason"] for problem in error.value.details["problems"]}


def test_wildcard_transition_is_an_edge_from_every_other_status() -> None:
    graph = WorkflowGraphDefinition(
        initial_status="open",
        statuses=_valid_graph().statuses,
        transitions=(
            _transition("open", "work"),
            _transition(None, "closed", resolution=True),
            _transition("closed", "open"),
        ),
    )

    validate_graph(graph)


def test_missing_fields_include_resolution_without_duplicates() -> None:
    transition = TransitionDefinition(
        name="Complete",
        source_status="work",
        target_status="closed",
        required_fields=("description", "resolution"),
        requires_resolution=True,
    )

    assert missing_required_fields(transition, {"description"}) == ("resolution",)
