# M8 Seeded Noise and Scaling

## Reproducibility contract

`NoiseConfig` is the complete run-level probability contract. It carries a stable `config_id`, a human-auditable `parameter_source`, and probabilities for one-qubit, two-qubit, reset, measurement, syndrome, imaging-loss, and parallel-Rydberg crosstalk channels. `SeededNoiseModel` hashes the seed together with the config, channel, task, and target identity for each draw. Replaying the same graph, schedule, config, and seed therefore produces the same trace and `NoiseReport`, independent of dictionary or loop order.

`noise-ideal.json` sets every channel to zero. `noise-illustrative.json` is deliberately labeled as synthetic software demonstration data; it is not fitted to a neutral-atom device or publication. Trace JSON records the config ID and seed, while ensemble JSON retains every shot and aggregate counts.

## Modeled effects

- One-qubit, two-qubit, and reset channels sample Pauli faults. Per-atom X/Z flags propagate through H and CZ using the supported symbolic Clifford rules.
- Measurement and syndrome channels can flip the reported classical bit independently of the stored Pauli flags.
- Imaging loss is accumulated and sampled only when an explicit `IMAGE_ATOMS` task begins. Loss becomes observable through the normal presence/loss observation contract.
- A two-qubit task counts other Rydberg tasks whose scheduled intervals overlap. Each neighbor adds the configured crosstalk probability to the base two-qubit probability, capped at one.
- Trajectories declare minimum clearance and maximum average polyline speed. Machine geometry rejects intersecting route pairs that do not share a finite conflict group.

The crosstalk rule is a transparent risk proxy, not a blockade-radius or optical-field simulation. Clearance is metadata plus corridor-level exclusion, not a continuous many-body collision proof. Acceleration, leakage, correlated spatial noise, loss misclassification, coherent error, pulse shape, and device drift are not modeled.

## Ensemble and scaling path

`run_noise_ensemble` schedules once and executes a unique seed for each shot. Its summary reports noise-event, loss, and observation counts per shot plus aggregate totals and means. The GHZ M8 workload contains one physical syndrome round, logical measurements, and a final surveillance image; the `d=5` form has 146 physical tasks and is covered by regression tests.

```powershell
$env:PYTHONPATH = "src;."
python examples/ghz_surface_code.py --distance 3 --profile low --noise-config examples/config/noise-illustrative.json --shots 16 --seed 100 --noise-summary artifacts/noise-d3.json
python examples/ghz_surface_code.py --distance 5 --profile high --noise-config examples/config/noise-ideal.json --shots 2 --seed 0
```

The ensemble validates deterministic replay, channel wiring, contention sensitivity, and tractable `d=5` execution. It does not calculate logical fidelity, establish a threshold, or validate the ideal erasure-aware decoder against calibrated correlated faults.

