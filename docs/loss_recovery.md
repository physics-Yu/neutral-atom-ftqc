# M7 Deterministic Atom-Loss Recovery

## Contract flow

```text
LossInjection
-> IMAGE_ATOMS detects absence
-> ATOM_LOSS observation / known erasure
-> LossManager / finite reservoir allocation
-> PLACE_ATOM -> RESET_ATOMS -> IMAGE_ATOMS
-> DagMutation revision + partial RESST schedule
-> physical syndrome round
-> IdealErasureAwareDecoder
-> RuntimeController resolves erasure
```

The lost atom and replacement atom always have different identities. `PLACE_ATOM` restores occupancy and `RESET_ATOMS` prepares the replacement in `|0>`; neither operation claims to reconstruct the erased data qubit. Future physical tasks are retargeted to the allocated atom ID through an explicit DAG transformation. A data site's `known_erasure` remains true in the final physical-execution snapshot and is cleared only after QEC and a `recovered` decoder result.

Ancilla loss follows a narrower policy: replacement, reset, and verification may resolve the vacancy because the ancilla is freshly prepared for later checks. Data and ancilla roles are therefore tested separately.

## Dynamic scheduling

Mutations are optimistic-concurrency updates against an exact graph ID/revision. Completed task IDs must be predecessor-closed and cannot be canceled. Canceled future tasks disappear; inserted tasks must have globally unique IDs and valid dependencies. The revised graph increments exactly one revision. RESST receives the observation time as `not_before_ns`, completed history, optional fixed active intervals, and the normal condition snapshot. The scheduler never reads atom-loss or stabilizer semantics.

## Deterministic demo assumptions

- Loss occurs at the start of a configured imaging task and becomes known at image completion.
- The demo preloads a finite number of reservoir atoms; it does not assume an infinite source.
- The reference erasure-aware decoder accepts fewer than `d` known erasures only after refill plus a new syndrome round. This is an ideal control-flow oracle, not a physical proof of correctability for arbitrary erasure geometry or correlated faults.
- The ideal backend returns zero stabilizer bits and does not simulate amplitude loss, leakage, correlated transport loss, or measurement error.
- Active in-flight intervals can be supplied as fixed intervals, but the bundled demo mutates at a task boundary where no instruction remains active.

These simplifications make event ownership, physical refill semantics, graph revisioning, and timing observable. M8 adds seeded accumulated imaging loss and Pauli/readout channels, but recovery correctness under correlated calibrated device noise remains future validation.

