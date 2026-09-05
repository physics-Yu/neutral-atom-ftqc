# neutral-atom-ftqc

Research-oriented prototype for compiling, scheduling, simulating, and visualizing fault-tolerant quantum-computing workflows on reconfigurable neutral-atom hardware.

The first target demonstration is logical GHZ-state preparation with surface-code logical qubits. The project will connect logical/QEC compilation to experimentally meaningful neutral-atom operations, RESST-style resource scheduling, a machine-level digital twin, QEC decoding, and atom-loss recovery.

## Intended execution stack

```text
Logical circuit
  -> QEC-aware compiler
  -> physical experimental IR / ISA
  -> RESST scheduler
  -> timed experimental instructions
  -> digital-twin execution
  -> syndrome / measurement / atom-loss events
  -> decoder + runtime feedback
```

The lowest executable layer contains only operations that an experimental platform can issue. Logical operations such as `LOGICAL_CNOT` and `SYNDROME_ROUND` are compiler abstractions and must be lowered before scheduling or execution.

## Current status

M0 through M8 are complete. The executable stack now includes compilation, physical scheduling, digital-twin execution, visualization, syndrome/decoder feedback, deterministic atom-loss recovery, and seeded configurable gate, measurement, syndrome, imaging-loss, and parallel-Rydberg crosstalk noise. Route geometry is audited for undeclared intersections and speed limits, while ensemble summaries and tests cover both `d=3` and `d=5`.

Run the complete measured baseline with `python examples/ghz_surface_code.py --distance 3 --execute --measure` after setting `PYTHONPATH=src;.` on Windows.

Generate the complete offline M5 comparison artifact with:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --visualize artifacts/ghz-d3.html --compare-resources
```

Open `artifacts/ghz-d3.html` directly in a browser. It embeds all data and code; `artifacts/ghz-d3.json` is emitted alongside it for inspection.

Run one explicit ideal syndrome/decoder cycle with:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --syndrome-rounds 1 --decode
```

Run and visualize the deterministic M7 recoverable-loss scenario with:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --inject-loss --visualize artifacts/ghz-loss-d3.html
```

Run the seeded M8 ensemble and emit both a statistical summary and a noisy trace artifact with:

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --profile low --noise-config examples/config/noise-illustrative.json --shots 16 --seed 100 --noise-summary artifacts/noise-d3.json --visualize artifacts/noise-d3.html
```

The bundled nonzero probabilities are explicitly synthetic demonstration inputs, not device calibration or a logical-fidelity claim. See `docs/noise_and_scaling.md` for semantics and limitations.

See `AGENTS.md` for project-wide constraints and `docs/architecture_and_implementation_plan.md` for the milestone plan.

完整的中文项目说明、目录导览、M0–M8 功能清单和复现命令见 [`docs/project_guide_zh.md`](docs/project_guide_zh.md)。



