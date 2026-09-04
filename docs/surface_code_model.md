# Surface-code model v0.1 (M1)

## Scope

M1 implements an abstract, distance-parameterized **rotated planar surface code** for logical/QEC compilation. It defines code sites, checks, logical supports, encoded blocks, and transversal pairings. It does not define pulse schedules, syndrome-extraction circuits, transport trajectories, or a claim of fault-tolerant physical CNOT execution; those remain later-milestone responsibilities.

## Layout convention

For odd `d >= 3`, the canonical generator creates:

- `d^2` data sites on a `d x d` grid;
- `d^2 - 1` measurement-ancilla sites;
- `(d^2 - 1) / 2` X checks and the same number of Z checks;
- weight-four interior checks and alternating weight-two boundary checks.

Coordinates are exact integer **half-trap-spacing lattice units**, not micrometers. Data sites occupy odd/odd coordinates. Interior ancillas occupy even/even coordinates, and boundary ancillas lie on the outer even coordinate. M2 must map these abstract coordinates to calibrated machine geometry and micrometers.

Interior plaquettes use X checks when `row + column` is even and Z checks otherwise. Boundary convention:

- X boundaries: top uses odd column segments; bottom uses even column segments.
- Z boundaries: left uses even row segments; right uses odd row segments.

The canonical logical X is the first data column and logical Z is the first data row. The constructor verifies:

- unique IDs and coordinates;
- exactly one check per ancilla;
- valid weight-two/four supports;
- pairwise X/Z stabilizer commutation;
- logical/stabilizer commutation;
- odd logical X/Z overlap, hence anticommutation.

The test suite also verifies that the generated stabilizer matrix has rank `d^2 - 1`, so the modeled patch encodes one logical qubit.

These conventions are deterministic and tested at `d=3` and `d=5`. Alternative boundary orientations or code families require a new `SurfaceCodeLayoutKind`; they must not be silently encoded as flags in this layout.

## Logical blocks and Pauli frame

`LogicalQubitBlock` combines a stable block ID, logical-qubit ID, and immutable layout. Local site IDs are qualified as `block-id/local-site-id`, preventing collisions when several blocks share one layout template.

`PauliFrame` is an immutable logical frame whose X/Z updates compose by XOR. Updating it records classical correction state only and does not apply a physical gate.

## QECProtocolIR

`expand_to_qec_protocol()` converts each declared logical qubit into an `EncodedBlock` and each logical operation into a QEC protocol macro with preserved dependencies and source provenance.

For `LOGICAL_CNOT`, M1 uses the explicitly selected strategy `transversal` and constructs a coordinate-matched bijection over all `d^2` data sites. The QEC IR validates equal distance, coordinate compatibility, correct control/target block ownership, and one-to-one coverage.

`TRANSVERSAL_CNOT`, `PREPARE_ZERO`, and `PREPARE_PLUS` remain QEC protocol macros. They are not members of the Physical Experimental ISA and cannot be sent to RESST or the digital twin. M2 must lower each macro to movement, alignment, physical pulses, and other physical tasks.

## GHZ dependency graph

The M1 example builds four blocks with `L0 = |+_L>` and `L1..L3 = |0_L>`, followed by:

```text
cx-L0-L1
   |\
   | +--> cx-L1-L3
   +----> cx-L0-L2
```

The two second-layer CNOTs share the first-layer predecessor but have no dependency on one another. Their physical parallelism is deliberately undecided until M2/M3 add geometry and resources.

Run the current example after installing the package in editable mode, or from the repository root with:

```powershell
$env:PYTHONPATH = "src"
python examples/ghz_surface_code.py --distance 3
```

## Deferred physics questions

- Exact syndrome-extraction gate ordering and hook-error orientation.
- Number of initialization and post-CNOT QEC rounds.
- Whether the selected physical platform supports the assumed blockwise transversal CNOT without rotation, basis changes, or additional fault-tolerance constraints.
- Trap spacing, physical coordinates, block orientation, movement, alignment, Rydberg parallelism, and crosstalk.
- Decoder choice and noise/loss models.

The M1 pairing is therefore a compiler contract to be reviewed against the target experiment before M2 declares the physical lowering device-ready.

