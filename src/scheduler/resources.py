"""Deterministic half-open capacity calendars for resources and zones."""

from __future__ import annotations

from dataclasses import dataclass

from compiler.physical_ir import ResourceDemand, ResourceMode, ZoneDemand
from contracts.common import ContractValidationError
from contracts.machine import MachineConfig
from scheduler.task import FixedInterval


@dataclass(frozen=True, slots=True)
class Reservation:
    interval_id: str
    start_ns: int
    end_ns: int
    quantity: int
    exclusive: bool = False


class CapacityCalendar:
    def __init__(self, machine: MachineConfig, fixed_intervals: tuple[FixedInterval, ...] = ()) -> None:
        self.resource_capacities = {item.resource_id: item.capacity for item in machine.resources}
        self.zone_capacities = {item.zone_id: item.capacity for item in machine.zones}
        self.resources: dict[str, list[Reservation]] = {key: [] for key in self.resource_capacities}
        self.zones: dict[str, list[Reservation]] = {key: [] for key in self.zone_capacities}
        for interval in sorted(fixed_intervals, key=lambda item: (item.start_ns, item.interval_id)):
            self._validate_demands(interval.resource_demands, interval.zone_demands)
            blockers = self.conflicts(interval.start_ns, interval.end_ns, interval.resource_demands, interval.zone_demands)
            if blockers:
                raise ContractValidationError(f"fixed interval {interval.interval_id!r} overbooks capacity")
            self.reserve(interval.interval_id, interval.start_ns, interval.end_ns, interval.resource_demands, interval.zone_demands)

    def earliest_slot(
        self, lower_bound_ns: int, duration_ns: int,
        resource_demands: tuple[ResourceDemand, ...], zone_demands: tuple[ZoneDemand, ...],
    ) -> tuple[int, tuple[str, ...]]:
        self._validate_demands(resource_demands, zone_demands)
        ends = {
            item.end_ns for reservations in (*self.resources.values(), *self.zones.values())
            for item in reservations if item.end_ns >= lower_bound_ns
        }
        blockers: set[str] = set()
        for start_ns in sorted({lower_bound_ns, *ends}):
            current = self.conflicts(start_ns, start_ns + duration_ns, resource_demands, zone_demands)
            if not current:
                return start_ns, tuple(sorted(blockers))
            blockers.update(current)
        raise AssertionError("finite reservations must always leave a later slot")

    def conflicts(
        self, start_ns: int, end_ns: int,
        resource_demands: tuple[ResourceDemand, ...], zone_demands: tuple[ZoneDemand, ...],
    ) -> tuple[str, ...]:
        blockers: set[str] = set()
        for demand in resource_demands:
            reservations = self.resources[demand.resource_id]
            overlapping = [item for item in reservations if item.start_ns < end_ns and start_ns < item.end_ns]
            if demand.mode is ResourceMode.EXCLUSIVE or any(item.exclusive for item in overlapping):
                blockers.update(item.interval_id for item in overlapping)
            else:
                blockers.update(self._capacity_blockers(start_ns, end_ns, demand.quantity, self.resource_capacities[demand.resource_id], overlapping))
        for demand in zone_demands:
            overlapping = [item for item in self.zones[demand.zone_id] if item.start_ns < end_ns and start_ns < item.end_ns]
            blockers.update(self._capacity_blockers(start_ns, end_ns, demand.quantity, self.zone_capacities[demand.zone_id], overlapping))
        return tuple(sorted(blockers))

    @staticmethod
    def _capacity_blockers(start_ns: int, end_ns: int, quantity: int, capacity: int, reservations: list[Reservation]) -> set[str]:
        blockers: set[str] = set()
        points = {start_ns, *(item.start_ns for item in reservations if start_ns <= item.start_ns < end_ns)}
        for point in points:
            active = [item for item in reservations if item.start_ns <= point < item.end_ns]
            if quantity + sum(item.quantity for item in active) > capacity:
                blockers.update(item.interval_id for item in active)
        return blockers

    def reserve(
        self, interval_id: str, start_ns: int, end_ns: int,
        resource_demands: tuple[ResourceDemand, ...], zone_demands: tuple[ZoneDemand, ...],
    ) -> None:
        for demand in resource_demands:
            self.resources[demand.resource_id].append(Reservation(
                interval_id, start_ns, end_ns, demand.quantity, demand.mode is ResourceMode.EXCLUSIVE,
            ))
        for demand in zone_demands:
            self.zones[demand.zone_id].append(Reservation(interval_id, start_ns, end_ns, demand.quantity))

    def _validate_demands(self, resource_demands: tuple[ResourceDemand, ...], zone_demands: tuple[ZoneDemand, ...]) -> None:
        for demand in resource_demands:
            if demand.resource_id not in self.resource_capacities or demand.quantity > self.resource_capacities[demand.resource_id]:
                raise ContractValidationError("resource demand cannot be satisfied by this machine")
        for demand in zone_demands:
            if demand.zone_id not in self.zone_capacities or demand.quantity > self.zone_capacities[demand.zone_id]:
                raise ContractValidationError("zone demand cannot be satisfied by this machine")
