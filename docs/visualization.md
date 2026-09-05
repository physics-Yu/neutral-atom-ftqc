# M5 Visualization

M5 supplies a read-only boundary from `PhysicalTaskGraph + TimedSchedule + ExecutionResult` to a versioned visualization bundle. `src/visualization/artifact.py` validates that every input names the same graph and schedule, then projects physical tasks, scheduling decisions, target geometry, execution events, snapshots, and observations. It never imports logical/QEC intent to make scheduling decisions and never mutates the source contracts.

## Artifact contract

`VisualizationBundle` contains one or more uniquely identified `VisualizationRun` values. Each run records:

- target zones, dimensions, finite capacities, resources, and configured trajectory conflict groups;
- physical opcode tasks with start/end times, operands, resources, zones, provenance, scheduler wait reasons, and blockers;
- replayable trace events, state snapshots, observations, makespan, resource wait, and peak parallelism.

`write_visualization_artifact` emits a standalone `.html` and an inspectable `.json` sidecar. The HTML embeds the JSON, CSS, and JavaScript and performs no network fetches, so it can be opened directly from disk.

## Synchronized views

One integer-nanosecond cursor drives all three views:

1. **Spatial state** renders configured zone geometry and trajectories. Blocks use the latest trace snapshot and interpolate only along an active, preconfigured trajectory.
2. **Resource Gantt** renders each task once on every claimed resource lane. Corridor lanes expose routing serialization and tooltips report wait reasons and blocking intervals.
3. **Event stream** follows task-start, task-completion, and observation events and highlights the event nearest the cursor.

The profile selector compares runs without changing their physical DAG. `examples/config/resources-low.json` retains single-capacity transport/control corridors; `resources-high.json` increases selected capacities. For the measured `d=3` fixture, the same 41 tasks take 1,266,400 ns on the low profile and 466,400 ns on the high profile, and the two logically parallel layer-two Rydberg operations overlap only in the latter.

## Reproduction

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --visualize artifacts/ghz-d3.html --compare-resources
pytest
```

## Explicit simplifications

- Spatial marks represent encoded blocks, not a to-scale drawing of every atom or optical field.
- Motion interpolation follows the configured waypoint polyline. Collision/conflict truth comes from the physical task's named corridor resources and M3/M4 validation, not from geometric intersection calculations in the viewer.
- The offline viewer replays a completed static trace; live device streaming and runtime DAG mutation are deferred.
- The deterministic symbolic backend validates execution and visualization contracts but does not establish encoded GHZ fidelity, noise performance, or experimental timing.
