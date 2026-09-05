"""Public facade for the RESST-style physical scheduler."""

from scheduler.resst import schedule_physical_tasks
from scheduler.task import ScheduleRequest, TimedSchedule


def schedule(request: ScheduleRequest) -> TimedSchedule:
    return schedule_physical_tasks(request)


__all__ = ["ScheduleRequest", "TimedSchedule", "schedule", "schedule_physical_tasks"]
