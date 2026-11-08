# Build phases

This is the build log of the project, one section per phase, matching one git
commit per phase. The problems listed are the ones actually hit while building.
Numbers in the generated blocks come from `results/*.csv` via `make report`.

> All data is fictional.

---

## Phase 1: Problem definition and fictional data design

**Objective.** Define the system, its boundary and the questions to answer.
Encode the fictional line in configuration, and design the input and
validation data sets.

**What was done**
- Wrote `config/line_parameters.yaml` with every value from the brief: shift,
  demand, product mix, batches, 7 stations, buffers, release rule, rework loop,
  simulation settings and a VSM snapshot block for each station.
- Wrote `config/scenarios.yaml` with an override language (`extends`, `scale`,
  `add`, station ranges) for S0-S5, plus S6 as an extension.
- Built `evapsim.config`: typed frozen dataclasses, range and consistency
  validation, and override resolution.
- Generated `data/time_study_samples.csv`: 40 observations per station from
  lognormal(mean, CV), seed 1101, rounded to 0.1 s.
- Started `docs/ASSUMPTIONS.md` (A1-A32).

**Key decisions and why**
- *Saturated line with CONWIP release* (A2, A8). Demand above capacity would
  otherwise make lead time depend on the length of the run.
- *Productive time only* (A3). It removes artificial shift-boundary effects.
- *Overrides on the dict form, then re-validated*. A scenario can never
  produce an invalid model.

**Problems and solutions**
- The brief asks for `observed_line_data.csv` in Phase 1, but it must come from
  "a slightly perturbed version of the model", which did not exist yet. The
  data dictionary and perturbation spec were fixed in Phase 1 (A28). The file
  itself was generated and committed in Phase 3 (A30).
- The project sits in a sub-folder of an existing portfolio repository, which
  already had git history, so `git init` was not needed (A29).

**Verification evidence.** `tests/test_config.py`: baseline values, takt =
75.79 s, mix multiplier 1.005, scale and range overrides, `extends` chains,
and five kinds of invalid configuration rejected.

**Outputs.** `config/*.yaml`, `data/time_study_samples.csv`,
`src/evapsim/config.py`, `distributions.py`, `datagen.py`,
`docs/ASSUMPTIONS.md`.

---

## Phase 2: Input analysis

**Objective.** Choose and justify the cycle-time distribution of each station.

**What was done.** Fitted lognormal, gamma and Weibull (MLE, location 0) to
each station's 40 observations. Compared them by AIC and screened with the KS
test. Checked that the specified mean lies in the sample's 95 % CI. Drew a
histogram with fitted densities and a Q-Q plot per station.

<!-- BEGIN:input_analysis -->
| Station | Sample mean (s) [95 % CI] | Spec mean in CI | Sample CV | Lowest AIC | Lognormal ΔAIC | KS p (lognormal) | Selected |
|---|---|---|---|---|---|---|---|
| S1 | 41.0 [39.3, 42.7] | yes | 0.131 | gamma | 0.10 | 0.95 | lognormal |
| S2 | 58.4 [54.8, 62.0] | yes | 0.193 | gamma | 0.51 | 0.97 | lognormal |
| S3 | 48.1 [46.1, 50.2] | yes | 0.133 | lognormal | 0.00 | 0.81 | lognormal |
| S4 | 78.2 [73.9, 82.5] | yes | 0.171 | weibull | 0.67 | 0.97 | lognormal |
| S5 | 60.5 [58.6, 62.4] | yes | 0.100 | lognormal | 0.00 | 0.17 | lognormal |
| S6 | 125.4 [118.8, 132.0] | yes | 0.165 | gamma | 0.37 | 0.67 | lognormal |
| S7 | 44.9 [43.6, 46.2] | yes | 0.090 | lognormal | 0.00 | 0.69 | lognormal |
<!-- END:input_analysis -->

**Key decisions and why.** Selection rule: candidates rejected by KS are
dropped. Lognormal is preferred when its ΔAIC ≤ 2 (statistically
indistinguishable, Burnham & Anderson), otherwise the lowest-AIC candidate is
used. Lognormal was selected for all stations. Gamma or Weibull had a
marginally lower AIC at four stations, but by less than 1 AIC unit every
time. Lognormal is also physically sensible, because cycle times are strictly
positive, right-skewed and driven by multiplicative effects. It is parameterised
directly by mean and CV, which is how the time-study standards are stated.

**Problems and solutions**
- `fontweight="semibold"` is not available in the DejaVu font that matplotlib
  ships with, which triggered warnings. Switched to `bold`.
- The first legends covered histogram bars. Added headroom to the y-axis and
  pinned the legend positions.

**Verification evidence.** `tests/test_distributions.py` recovers the mean and
CV of 400 000 lognormal draws to within 0.5 % / 2 %, and recovers a known
lognormal by fitting. The specified mean lies inside the sample CI at all 7
stations.

**Outputs.** `results/input_analysis.csv`, `results/figures/input_fit_S1..S7.png`.

---

## Phase 3: Core model

**Objective.** Build a SimPy model with every mechanism in the brief and
measure everything in it.

**What was done.** `evapsim.model`: one process per machine, finite buffers
(a priority store plus a slot container) with blocking after service,
operation-dependent exponential failures, changeovers on model switch, scrap,
the leak-test → brazing rework loop, CONWIP/unlimited release, and per-unit
timestamps. Each machine's time is split into busy, starved, blocked, down and
changeover, per day. Time-weighted WIP and buffer levels are clipped to the
measurement window, and batch lead times are recorded. Generated
`data/observed_line_data.csv` from a perturbed copy of the model.

**Key decisions and why**
- *One SimPy process per server, not `simpy.Resource`*. Each machine's state
  can then be timed exactly, and a blocked machine keeps hold of its unit.
- *Rework enters a priority lane without a buffer slot* (A17). If rework units
  had to use the 4→5 buffer, the loop could deadlock (S5 waiting on a full S4
  input while S4 waits on a full 4→5 buffer).
- *Common random numbers by construction* (A18). Each unit carries its own
  pre-drawn normals and uniforms, taken in release order. Failure and
  changeover draws come from separate per-machine streams, and are generated as
  standard variates and then scaled.

**Problems and solutions**
- The first design shared one random stream per machine for failures and
  changeovers. Changing changeover times (SMED) would then shift every later
  failure draw and weaken the pairing between scenarios. Split into separate
  failure and changeover streams.
- `if co_mu:` was used to test whether a station has changeovers. The
  lognormal location `mu` can be zero or negative, so this was a latent bug.
  Replaced with an explicit `has_co` flag.
- The baseline came out at about 230 units/day against a demand of 380. Before
  accepting this, it was checked against a static capacity calculation (Phase
  5): brazing needs about 112.6 s per unit including failures, changeovers and
  rework, against a takt of 75.8 s. The shortfall is therefore built into the
  brief's numbers, not a bug, and the parameters were kept unchanged (A20).

**Verification evidence.** First single run: Little's-law WIP 19.13 against a
measured WIP of 19.14. Brazing changeovers per batch ≈ 0.62 × batches, as
expected.

**Outputs.** `src/evapsim/model.py`, `data/observed_line_data.csv`.

---

## Phase 4: Metrics

**Objective.** Turn raw replication output into the KPIs in the brief.

**What was done.** `evapsim.metrics`: throughput, takt compliance, attainment,
lead time (mean/P50/P90/P95, units and batches), WIP and Little's-law WIP,
line FPY and RTY, scrap share, VA time and VA ratios, station state shares,
uptime, days of stock, failures and changeovers per day, bottleneck, Student-t
CIs and paired-t differences.

**Key decisions and problems**
- **Bottleneck rule.** The brief defines the bottleneck as the "station with
  the highest busy+blocked share". Implemented literally, it chose **S1** in
  100 % of baseline replications, because S1 is blocked about 60 % of the time
  *by* the brazing constraint. Switched to the standard active-period method
  (busy + down + changeover), which chooses S4. The literal rule is still
  computed (`bottleneck_busy_blocked_rule`,
  `share_busy_plus_blocked_rule`) so the comparison stays visible (A21).
- **Uptime** is defined as busy / (busy + down). With operation-dependent
  failures this estimates MTBF/(MTBF+MTTR), which makes it comparable with the
  VSM snapshot.
- ruff's SIM108 rule (prefer a ternary) made the paired-test code harder to
  read, so it was disabled.

**Verification evidence.** The baseline station table (below) shows S4 with the
highest active share, and upstream stations mostly blocked and downstream
stations mostly starved, which is the expected pattern around a bottleneck.

<!-- BEGIN:baseline_states -->
| Station | Busy | Changeover | Down | Blocked | Starved | Active (bottleneck metric) | Avg. units in front |
|---|---|---|---|---|---|---|---|
| S1 Tube Cut & Bend | 35.8 % | 0.0 % | 2.6 % | 61.6 % | 0.0 % | 38.4 % | - |
| S2 Fin-Pack Assembly | 46.6 % | 15.8 % | 2.3 % | 33.7 % | 1.5 % | 64.8 % | 4.86 |
| S3 Tube Expansion | 40.5 % | 0.0 % | 2.2 % | 48.3 % | 9.0 % | 42.7 % | 3.60 |
| S4 Header Brazing | 65.9 % | 19.0 % | 9.2 % | 2.6 % | 3.3 % | 94.0 % | 4.53 |
| S5 Pressure & Leak Test | 49.9 % | 0.0 % | 3.6 % | 0.0 % | 46.5 % | 53.5 % | 0.21 |
| S6 Casing & Final Assembly | 48.6 % | 0.0 % | 0.0 % | 0.0 % | 51.4 % | 48.6 % | 0.02 |
| S7 Inspection & Packing | 36.4 % | 0.0 % | 0.0 % | 0.0 % | 63.6 % | 36.4 % | 0.02 |
<!-- END:baseline_states -->

**Outputs.** `src/evapsim/metrics.py`.

---

## Phase 5: Monte Carlo runner

**Objective.** Run many independent, reproducible replications in parallel
and decide how many are needed.

**What was done.** `evapsim.runner`: replication *r* uses
`SeedSequence(base_seed, spawn_key=(r, ...))`, the same keys
`SeedSequence.spawn` would produce. Work is split into chunks over a process
pool. The module also aggregates KPI, station, daily, batch and lead-time
histogram tables, and computes the convergence analysis. Added the
`python -m evapsim` CLI and the static capacity hand calculation.

<!-- BEGIN:convergence -->
| Metric | Target CI half-width | Replications required | Achieved with run |
|---|---|---|---|
| throughput_per_day | ±0.5 % | 152 | ±0.27 % (500 reps) |
| throughput_per_day | ±1 % | 40 | ±0.27 % (500 reps) |
| throughput_per_day | ±2 % | 12 | ±0.27 % (500 reps) |
| lt_mean_min | ±0.5 % | 175 | ±0.29 % (500 reps) |
| lt_mean_min | ±1 % | 46 | ±0.29 % (500 reps) |
| lt_mean_min | ±2 % | 14 | ±0.29 % (500 reps) |
<!-- END:convergence -->

**Key decisions.** 500 replications are far more than the 40 needed for ±1 %.
They were kept because the brief asks for them and because they make the
P95 lead-time and takt-compliance estimates stable. Quick mode (50
replications) still reaches about ±1 %.

**Problems and solutions**
- In the convergence figure, the CI at n = 2 stretched the y-axis so far that
  the running mean looked flat. The axis is now limited to the range from n ≥ 10.
- Python 3.13 warns that `fork()` in a multi-threaded process may deadlock
  (pytest and Streamlit both run threads). Switched the pool to the `spawn`
  context, which is also the default on macOS and Windows.

**Verification evidence.** `test_parallel_equals_serial` (identical tables for
1 and 3 workers) and `test_quick_reps_are_prefix_of_full_run`. Re-running the
baseline produced byte-identical CSV files.

**Outputs.** `results/baseline_*.csv`, `results/convergence*.csv`,
`results/static_capacity.csv`, `results/figures/baseline_*.png`,
`results/figures/convergence.png`.

---

## Phase 6: Verification and validation

**Objective.** Show that the model is built right (verification) and that it
is the right model (validation).

**Verification (tests/).** 35 automated checks were added in this phase. The
suite has 40 tests at release. They include:
- Deterministic mode (zero variance, no failures, scrap or changeovers):
  throughput = 28 800 s / 78 s = 369.2 units/day, and every day produces 369 or
  370 units.
- With two brazing fixtures, the deterministic bottleneck moves to S6 (120 s / 2
  = 60 s → 480/day).
- A changeover hand calculation with two models: busy + changeover + 145 s
  initial fill = horizon exactly, changeover time = 720 s × number of switches,
  and output = brazing busy time / 78 s.
- Little's law (WIP = TH × LT) within 3 % per replication. Across the baseline
  means the two agree to 0.01 %.
- Conservation: released = departed + in line, and every departure is either
  good or scrap.
- CONWIP cap never exceeded. Unlimited release is bounded by physical capacity.
- Timestamps strictly ordered along the routing. State shares sum to 1.
- Rework stress test (40 % test failures, all reworked, buffer size 1): no
  deadlock.
- Smaller buffers cause more blocking and less throughput.
- Reproducibility, seed sensitivity, and positive CRN correlation.

**Problem found by a test.** The first version of the two-fixture test
expected the bottleneck to move to Fin-Pack (55 s). It actually moved to Final
Assembly at 60 s per unit, because 120 s spread over 2 workstations is still
slower than 55 s. The model was right and the hand calculation was wrong. In
the *stochastic* S3 scenario the bottleneck does move to S2, because S2 also
loses 16 % of its time to changeovers. Both cases are now explained in the
tests.

**Validation.** The nominal model was compared with the 20 observed days from
the perturbed line:

<!-- BEGIN:validation -->
| Measure | Observed | Simulated | Error | Sim. 95 % PI | PI p-value | Welch p | Verdict |
|---|---|---|---|---|---|---|---|
| Mean daily output (units/day) | 230.4 | 231.1 | +0.30 % | [215.2, 245.0] | 0.87 | 0.86 | valid |
| Mean batch lead time (min) | 72.0 | 71.4 | -0.91 % | [67.5, 76.8] | 0.69 | 0.62 | valid |
| Station utilisation (7 stations) | - | - | mean abs. 0.89 pp; worst S4 -5.2 % | - | - | - | valid |
<!-- END:validation -->

Both headline measures are within the 5 % target, and the observed 20-day
means lie well inside the simulated 95 % prediction intervals, so **no
calibration was needed**. The station-level comparison does pick up the
largest hidden perturbation: brazing's cycle time is 4.7 % longer in the
"real" line, and S4 is the station with the largest utilisation error. In a
real study this would trigger a new S4 time study before the model is used to
set brazing targets. It was not used to tune the model, in line with SOP §9.5.

**Outputs.** `tests/`, `src/evapsim/validation.py`,
`results/validation_summary.csv`, `results/validation_station_utilisation.csv`,
`results/vsm_observed_vs_simulated.csv`, `results/figures/validation.png`.

---

## Phase 7: Scenarios and sensitivity

**Objective.** Quantify each improvement with statistical confidence and rank
the parameters that drive throughput.

**What was done.** Ran S0-S6 with 500 replications each, using common random
numbers, and computed paired differences against S0 with 95 % CIs. Ran a
one-at-a-time sensitivity design with 18 factors × 2 levels × 100
replications, also paired, and drew a tornado chart. Swept the CONWIP limit
(10-60) for S0 and S5 to get the WIP-throughput-lead time operating curve.
This turned the buffer and WIP finding into a quantified recommendation.

<!-- BEGIN:scenarios -->
| Scenario | TH (units/day) | ΔTH vs S0 [95 % CI] | ΔTH % | p (paired t) | Takt compliance | LT mean (min) | ΔLT vs S0 [95 % CI] | WIP | Bottleneck |
|---|---|---|---|---|---|---|---|---|---|
| **S0** Baseline | 231.1 | - | - | - | 0.0 % | 37.9 | - | 19.0 | S4 (100 %) |
| **S1** Larger buffers | 237.0 | +5.9 [5.8, 6.1] | +2.6 % | < 0.001 | 0.0 % | 65.8 | +27.9 [27.8, 28.0] | 33.8 | S4 (100 %) |
| **S2** SMED | 250.5 | +19.4 [19.2, 19.6] | +8.4 % | < 0.001 | 0.0 % | 36.3 | -1.6 [-1.6, -1.6] | 19.7 | S4 (100 %) |
| **S3** Second brazing fixture | 302.6 | +71.5 [70.9, 72.0] | +30.9 % | < 0.001 | 0.6 % | 29.8 | -8.1 [-8.1, -8.0] | 19.5 | S2 (100 %) |
| **S4** Preventive maintenance | 243.4 | +12.3 [12.1, 12.6] | +5.3 % | < 0.001 | 0.0 % | 36.3 | -1.6 [-1.6, -1.5] | 19.1 | S4 (100 %) |
| **S5** Combined (SMED + PM + buffers 8) | 268.2 | +37.1 [36.9, 37.4] | +16.1 % | < 0.001 | 0.0 % | 49.2 | +11.3 [11.3, 11.4] | 28.6 | S4 (100 %) |
| **S6** Combined + second fixture (extension) | 374.7 | +143.6 [143.0, 144.2] | +62.1 % | < 0.001 | 48.5 % | 30.0 | -7.8 [-7.9, -7.7] | 24.3 | S2 (100 %) |
<!-- END:scenarios -->

<!-- BEGIN:sensitivity -->
| Factor | −10 % (buffers −1) | +10 % (buffers +1) | Elasticity (+) |
|---|---|---|---|
| S4 cycle time | +16.6 [16.3, 17.0] | -14.9 [-15.3, -14.5] | -0.64 |
| S4 MTBF | -2.5 [-2.9, -2.1] | +2.1 [1.7, 2.4] | +0.09 |
| All buffer sizes (±1 unit) | -2.8 [-3.0, -2.7] | +1.6 [1.5, 1.7] | +0.03 |
| S4 MTTR | +2.1 [2.0, 2.3] | -2.1 [-2.2, -1.9] | -0.09 |
| S5 MTTR | +0.8 [0.7, 0.9] | -0.8 [-0.9, -0.7] | -0.03 |
| S5 cycle time | +0.6 [0.4, 0.8] | -0.7 [-0.9, -0.4] | -0.03 |
| S5 MTBF | -0.7 [-0.9, -0.5] | +0.5 [0.2, 0.7] | +0.02 |
| S2 cycle time | +0.6 [0.4, 0.7] | -0.5 [-0.7, -0.4] | -0.02 |

_Change in throughput (units/day) against the baseline, as a paired mean with its 95 % CI. Factors are ranked by swing. Source: `results/sensitivity_oat.csv`._
<!-- END:sensitivity -->

**Key decisions.** S6 (S5 + a second fixture) was added after seeing that no
scenario in the brief reaches takt (A31). Buffer sensitivity uses ±1 unit
because ±10 % of 5 is not an integer (A32).

**Problems and solutions**
- Adding a second brazing fixture (S3) doubled brazing *changeovers*, because
  each fixture changes over on its own. Per fixture, the changeover share rose
  from 19 % to 24 %. This is a real effect of the modelling choice (A13), not a
  bug, and it makes the case for combining S3 with SMED (S6).
- Larger buffers (S1) increased WIP and lead time much more than throughput.
  Under CONWIP with a limit of 40, extra buffer space only fills with WIP. This
  is reported as a finding, not tuned away.
- The sensitivity design (37 runs of 100 replications) took far longer than
  its simulation time. Each run created a new `spawn` process pool, so every
  run paid the cost of re-importing NumPy, SciPy and pandas in each worker.
  Switched to one persistent pool per worker count, with a fallback to serial
  execution if the pool breaks. Results are unchanged, because seeds are keyed
  by replication and not by worker.
- A report test checked generated tables for the string "nan" and failed on
  "mainte**nan**ce". It now uses a word-boundary match.

<!-- BEGIN:conwip -->
| Scenario | CONWIP limit | TH (units/day) | ΔTH vs limit 40 [95 % CI] | WIP | LT mean (min) | LT P95 (min) |
|---|---|---|---|---|---|---|
| S0 | 10 | 214.2 | -16.9 [-17.4, -16.5] | 9.7 | 21.0 | 40.8 |
| S0 | 15 | 228.7 | -2.4 [-2.6, -2.2] | 14.3 | 28.9 | 56.0 |
| S0 | 20 | 230.9 | -0.2 [-0.2, -0.2] | 18.1 | 36.1 | 67.8 |
| S0 | 25 | 231.1 | -0.0 [-0.0, 0.0] | 18.9 | 37.8 | 71.0 |
| S0 | 30 | 231.1 | +0.0 [0.0, 0.0] | 18.9 | 37.8 | 71.0 |
| S0 | **40** | 231.1 | - | 18.9 | 37.8 | 71.0 |
| S0 | 60 | 231.1 | +0.0 [0.0, 0.0] | 18.9 | 37.8 | 71.0 |
| S5 | 10 | 256.5 | -11.8 [-12.2, -11.4] | 9.8 | 17.8 | 31.2 |
| S5 | 15 | 265.1 | -3.2 [-3.4, -2.9] | 14.7 | 25.8 | 44.3 |
| S5 | 20 | 267.2 | -1.1 [-1.2, -0.9] | 19.6 | 33.9 | 57.1 |
| S5 | 25 | 268.0 | -0.3 [-0.3, -0.2] | 24.4 | 42.0 | 69.4 |
| S5 | 30 | 268.3 | -0.0 [-0.0, -0.0] | 28.0 | 48.1 | 78.0 |
| S5 | **40** | 268.3 | - | 28.6 | 49.1 | 80.0 |
| S5 | 60 | 268.3 | +0.0 [0.0, 0.0] | 28.6 | 49.1 | 80.0 |

_Paired against the scenario at its configured limit (bold), 100 replications per point. Source: `results/conwip_sweep.csv`, figure `results/figures/conwip_sweep.png`._
<!-- END:conwip -->

**Outputs.** `results/scenario_*.csv`, `results/sensitivity_oat.csv`,
`results/conwip_sweep.csv`, `results/figures/scenario_*.png`,
`results/figures/sensitivity_tornado.png`, `results/figures/conwip_sweep.png`.

---

## Phase 8: VSM visualisation

**Objective.** Show the current-state and future-state (S5) value stream
maps, with simulated numbers.

**What was done.** `evapsim.vsm` draws the standard VSM icons in matplotlib:
supplier and customer factories, production control, process and data boxes
(C/T, C/O, uptime, FPY, utilisation, operators), inventory triangles (units and
days), push arrows, the CONWIP loop, trucks, kaizen bursts and the timeline
ladder. The waits on the ladder come from Little's law. Everything on a
machine beyond the cycle time is shown as "other delays", so the ladder adds up
to the simulated lead time.

<!-- BEGIN:vsm_summary -->
| VSM measure | Current (S0) | Future (S5) |
|---|---|---|
| Throughput (units/day) | 231.1 | 268.2 |
| Line lead time (min) | 37.9 | 49.2 |
| Value-added time per unit (s) | 452 | 452 |
| VA ratio, line (%) | 19.9 | 15.3 |
| Door-to-door lead time (days) | 5.08 | 5.10 |
| VA ratio, door-to-door (%) | 0.31 | 0.31 |
| Line WIP (units) | 19.0 | 28.6 |
<!-- END:vsm_summary -->

**Problems and solutions**
- A naive ladder (buffer waits + cycle times) adds up to *less* than the
  simulated lead time, because blocking, breakdowns and changeovers while a
  unit is on a machine are not waits in a buffer. Rather than hide the
  difference, it is shown as an explicit "other delays" figure.
- In S5 the future-state lead time is *longer* than the current state's. The
  larger buffers (5 → 8) hold more WIP under the same CONWIP limit. This is
  shown on the map rather than hidden, and recommendation 3 in the README
  (cut buffers to 5 and the CONWIP limit to about 25) follows from it.

**Outputs.** `docs/vsm_current.png`, `docs/vsm_future.png`,
`results/vsm_data.csv`, `results/vsm_summary.csv`.

---

## Phase 9: Dashboard

**Objective.** Let a user explore scenarios and parameters without writing
code.

**What was done.** `app/dashboard.py` (Streamlit) offers a scenario picker,
inputs for demand, buffers, release rule, CONWIP limit and batch size, an
editable station table, and settings for replications, days and workers. It
shows KPI tiles with paired deltas against S0 and CIs in the tooltips, the
lead-time distribution, the station state bar, the bottleneck frequency, and a
scenario comparison (this run against S0, plus the committed full results).
Runs are cached by the full configuration.

**Problems and solutions**
- Streamlit 1.67 deprecates `use_container_width`. Switched to
  `width="stretch"` and raised the minimum version in `requirements.txt` to
  1.50.
- Running the app from a fresh clone without `pip install -e .`: the app adds
  `src/` to `sys.path` itself.

**Verification evidence.** `tests/test_dashboard.py` uses Streamlit's
`AppTest` to load the app, set 5 replications and 5 days, press Run and check
the KPI tiles, with no exceptions. The app was also launched with
`streamlit run` and checked in a headless browser.

**Outputs.** `app/dashboard.py`, `tests/test_dashboard.py`.

---

## Phase 10: Documentation and polish

**Objective.** Make the project understandable, reproducible and consistent.

**What was done.** README, MODEL_DESCRIPTION, OPERATING_PROCEDURES, this file,
and an executed `notebooks/analysis.ipynb`. `evapsim.report` writes every
results table in the README and docs from `results/*.csv` (`make report`).
Added a Makefile (`setup`, `test`, `baseline`, `scenarios`, `dashboard`, `all`,
`quick`) and a GitHub Actions workflow (ruff, pytest, 10-replication smoke run
on Python 3.11 and 3.12). A root-level copy of the workflow runs it in its
current sub-folder (A29).

**Problems and solutions**
- The report generator's regular expression did not match empty marker blocks
  (`BEGIN` directly followed by `END`), so the first `make report` filled
  nothing in the README. Fixed the pattern, and confirmed that running
  `make report` twice gives an identical file.
- The notebook printed the S5 paired-t p-value as `0.0e+00` (floating-point
  underflow). It is now reported as `< 0.001`.
- Numbers typed into documentation drift away from the results over time.
  Every results table is now a generated block between `BEGIN`/`END` markers,
  and the remaining hand-written numbers were checked against the CSV files in
  a final consistency pass.

**Verification evidence.** `make all` was run from a clean clone, ruff
reports "All checks passed!", and pytest is green.

**Outputs.** `README.md`, `docs/*.md`, `notebooks/analysis.ipynb`, `Makefile`,
`.github/workflows/ci.yml`.
