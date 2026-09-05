# M6 Syndrome, Decoder, and Pauli-Frame Runtime

## Definition of done

M6 is complete when a surface-code syndrome macro lowers entirely to Physical ISA v0.1 tasks, executes to typed syndrome observations, passes through an explicit decoder contract, updates software Pauli frames without mandatory correction pulses, and releases a physical continuation only after a decoder condition and modeled latency. The same interfaces and interaction construction must work at `d=3` and `d=5`.

Acceptance coverage includes QEC/physical serialization round trips, collision-free interaction layers, ideal syndrome execution, history windows, unique single-X/Y/Z lookup, ambiguous signatures, known-erasure deferral, decoder-result replay, frame XOR composition, condition blocking, decoder release time, and complete d=3/d=5 runtime cycles. The full repository command remains `pytest`.

## Physical extraction circuit

`SYNDROME_ROUND` exists only in logical/QEC IR. The compiler copies every stabilizer edge into an explicit `SyndromeInteraction` and assigns it to one of eight layers:

- layers 0–3 contain Z checks ordered by the four diagonal data/ancilla directions;
- layers 4–7 contain X checks using the same direction partition;
- X- and Z-check phases are separated so one data atom is never addressed twice in a layer.

For each block and round, lowering emits ancilla reset and Hadamard preparation in storage, block transport to entangling, align/CZ pairs for each populated layer, data Hadamards around the X-check phase, ancilla Hadamards before readout, explicit transport through storage to readout, ancilla measurement, and return transport. All operations use the existing experimental opcodes and retain logical/QEC provenance.

The interaction order is a deterministic collision-free reference schedule, not a proof of circuit-level fault tolerance. Hook-error orientation, repeated noisy rounds, leakage, measurement error, crosstalk, and device-calibrated pulse decomposition remain future physics work.

## Syndrome and decoder contracts

A syndrome observation identifies its block, logical qubit, layout, round index, every check bit, source task, and observation time. `SyndromeHistory` rejects duplicate block/round pairs, time reversal, and non-increasing rounds, and can select the latest window for one block.

`IdealSingleErrorDecoder` computes detection events by XORing the newest two samples, with an implicit zero baseline for the first sample. It returns:

- `clean` for no detection events;
- `corrected` only when the signature uniquely matches one data-site X, Y, or Z error;
- `ambiguous` rather than guessing when zero or multiple candidates match;
- `needs_recovery` for known erasures when using the M6-only decoder.

M7 adds `IdealErasureAwareDecoder`. After an explicit physical refill and a new syndrome round, it reports `recovered` for a correctable known-erasure set and `uncorrectable` when the erasure count reaches the code distance. This is a deterministic control-flow oracle, not a threshold-quality decoder.

The decoder latency is a positive injected integer in nanoseconds. The reference value is 25,000 ns and is a software-model parameter, not a measured decoder benchmark.

## Runtime feedback

`RuntimeController` consumes only `ObservationBatch`, layouts, the current logical frame, and the sparse physical frame. Each decoder result carries a `PauliFrameDelta`. Physical corrections toggle sparse site-level X/Z flags by XOR; logical X/Z flags remain a separate frame. No physical correction gate is emitted merely because a frame changes.

For every decoded block the controller publishes a stable `decoder-ready:*` condition whose availability equals decoder completion. A generated Physical ISA `emit_sync` continuation contains those `ConditionRef` values and an `earliest_start_ns` equal to the latest completion. M7 additionally permits erasure resolution only for a `recovered` decoder result; refill and reset alone cannot clear a data erasure.

## Ideal-backend boundary

The M6 ideal backend still does not simulate amplitudes or fault propagation. It executes every ancilla pulse/CZ/measurement state transition but returns stabilizer eigenvalue zero through the replaceable `StateBackend.syndrome_bit` method. Synthetic single-Pauli syndrome fixtures test decoder semantics independently. Therefore M6 demonstrates correct software boundaries and control flow, not logical error rate, GHZ fidelity, threshold behavior, or experimental correctness.

