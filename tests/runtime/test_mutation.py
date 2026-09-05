from __future__ import annotations

import pytest

from compiler.physical_ir import (
    PhysicalInstruction, PhysicalOpcode, PhysicalTask, PhysicalTaskGraph,
    ResourceDemand, ResourceMode, ZoneDemand,
)
from contracts import ContractValidationError
from examples.ghz_surface_code import build_profile_target
from runtime.mutation import DagMutation, apply_dag_mutation, reschedule_after_mutation


def _sync(task_id: str, predecessors: tuple[str, ...] = ()) -> PhysicalTask:
    return PhysicalTask(
        task_id,
        PhysicalInstruction(PhysicalOpcode.EMIT_SYNC, (), {
            "tag": task_id, "channel": "test",
        }),
        predecessors=predecessors,
        resource_demands=(ResourceDemand("clock-0", mode=ResourceMode.SHARED),),
        zone_ids=("storage",), zone_demands=(ZoneDemand("storage", 1),),
    )


def test_mutation_preserves_completed_history_cancels_future_and_reschedules_insertions() -> None:
    target = build_profile_target("low")
    first, obsolete = _sync("first"), _sync("obsolete", ("first",))
    graph = PhysicalTaskGraph("dynamic", 4, (first, obsolete))
    replacement = _sync("replacement", ("first",))
    mutation = DagMutation(
        "loss-branch", graph.graph_id, graph.revision, 1_000,
        ("first",), ("obsolete",), (replacement,),
    )
    result = reschedule_after_mutation(graph, mutation, target.machine)

    assert result.graph.revision == 5
    assert result.graph.tasks[0] is first
    assert {task.task_id for task in result.graph.tasks} == {"first", "replacement"}
    assert [entry.task_id for entry in result.schedule.entries] == ["replacement"]
    assert result.schedule.entries[0].start_ns >= mutation.observed_at_ns
    assert DagMutation.from_json(mutation.to_json()) == mutation


def test_mutation_rejects_canceling_completed_history() -> None:
    graph = PhysicalTaskGraph("dynamic", 0, (_sync("first"),))
    with pytest.raises(ContractValidationError, match="completed task cannot be canceled"):
        DagMutation("bad", "dynamic", 0, 0, ("first",), ("first",))


def test_mutation_rejects_stale_graph_revision() -> None:
    graph = PhysicalTaskGraph("dynamic", 1, (_sync("first"),))
    mutation = DagMutation("stale", "dynamic", 0, 0, (), ())
    with pytest.raises(ContractValidationError, match="graph revision"):
        apply_dag_mutation(graph, mutation)

