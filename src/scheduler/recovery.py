"""Compatibility imports for the M7 runtime-owned mutation boundary.

Recovery policy lives in :mod:`loss`; DAG mutation lives in :mod:`runtime`.
The scheduler remains a consumer of generic physical graphs.
"""

from runtime.mutation import (
    DagMutation, RescheduleResult, apply_dag_mutation, reschedule_after_mutation,
)

__all__ = [
    "DagMutation", "RescheduleResult", "apply_dag_mutation",
    "reschedule_after_mutation",
]

