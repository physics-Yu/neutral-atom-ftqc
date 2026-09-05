# M5 Visualization

M5 supplies a read-only boundary from `PhysicalTaskGraph + TimedSchedule + ExecutionResult` to a versioned visualization bundle. `src/visualization/artifact.py` validates that every input names the same graph and schedule, then projects physical tasks, scheduling decisions, target geometry, execution events, snapshots, and observations. It never imports logical/QEC intent to make scheduling decisions and never mutates the source contracts.

## Artifact contract

`VisualizationBundle` contains one or more uniquely identified `VisualizationRun` values. Each run records:

- target zones, dimensions, finite capacities, resources, and configured trajectory conflict groups;
- physical opcode tasks with start/end times, operands, resources, zones, provenance, scheduler wait reasons, and blockers;
- replayable trace events, state snapshots, observations, makespan, resource wait, peak parallelism, and M8 noise metadata/events when present.

`write_visualization_artifact` emits a standalone `.html` and an inspectable `.json` sidecar. The HTML embeds the JSON, CSS, and JavaScript and performs no network fetches, so it can be opened directly from disk.

## Synchronized views

One integer-nanosecond cursor drives all three views:

1. **Spatial state** renders configured zone geometry and trajectories. Blocks use the latest trace snapshot and interpolate only along an active, preconfigured trajectory.
2. **Resource Gantt** renders each task once on every claimed resource lane. Corridor lanes expose routing serialization and tooltips report wait reasons and blocking intervals.
3. **Event stream** follows task-start, task-completion, typed observations, and runtime recovery events and highlights the event nearest the cursor.

The profile selector compares runs without changing their physical DAG. `examples/config/resources-low.json` retains single-capacity transport/control corridors; `resources-high.json` increases selected capacities. For the measured `d=3` fixture, the same 41 tasks take 1,266,400 ns on the low profile and 466,400 ns on the high profile, and the two logically parallel layer-two Rydberg operations overlap only in the latter.

## Reproduction

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --visualize artifacts/ghz-d3.html --compare-resources
pytest
```

## Explicit simplifications

- Spatial marks represent encoded blocks, not a to-scale drawing of every atom or optical field.
- Motion interpolation follows the configured waypoint polyline. Collision/conflict truth comes from the physical task's named corridor resources and geometry validation, not from the viewer.
- M7 can merge multiple absolute-time execution segments and runtime mutation events into one offline timeline; this remains replay visualization rather than live device streaming.
- The deterministic symbolic backend plus seeded M8 fault overlay validates execution, replay, and statistical plumbing but does not establish encoded GHZ fidelity, calibrated noise performance, or experimental timing.

