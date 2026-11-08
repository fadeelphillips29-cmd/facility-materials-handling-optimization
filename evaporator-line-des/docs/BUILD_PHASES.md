# Build phases (v2)

This is the build log, with one git commit per phase. The problems listed are
the real ones hit during the build. Generated tables come from `results/` via
`make report`.

> Illustrative and anonymised data ("the Company").

---

## Phase 1: Process mapping and data design

**Objective.** Turn the 14-step written flow and the colour-coded flowchart into
a model specification: process map, data dictionary with source tags, and a
hand-calculated VSM.

**What was done**
- `config/line_parameters.yaml` holds every input, each tagged *time study*,
  *estimate* or *assumed*. There is a global `time_scale_factor`, and the
  ambiguous flowchart order is configurable through `wash_before_test`.
- `evapsim.config` validates the inputs (departments, sources, ranges,
  resources), applies the time scaling and crew-efficiency adjustment, and
  resolves scenario overrides (`extends`, `scale`, `add`).
- `docs/process_flow.png` (matplotlib) and a mermaid map in the README use
  the brief's colour code.
- The hand-calculated VSM (`results/vsm_hand_calc.csv`) and the resource loads
  are computed by `equations.py`.
- `ASSUMPTIONS.md` contains the input register, which is generated from the
  YAML.

**Decisions and why**
- *Clock = working minutes* (A15) and *calendar delays as lognormal lead times*
  (A3, A10). Supplier capacity is outside the scope.
- *The fin-press operator is shared with boxing* (A6), and *the sheet-metal
  assembler is shared by plenum and drip tray*, because the brief says so.
- *Tube-dependent steps* include header preparation (A5). This is stated as an
  assumption, because the brief does not say what headers are made of.

**Problems and fixes**
- The first `process_flow.png` had the title overlapping a node and arrows
  leaving the canvas. The layout was redone on a column grid, with procurement
  boxes next to the rows they feed.
- Hand-calc rows inside one step came out in alphabetical order (flat welding
  before press brake). A sequence key from the config order fixed this.
- The project replaces the v1 flow-line prototype in the same folder (A33). v1
  stays in the history at `09a967f`.

**Outputs.** `config/`, `src/evapsim/config.py`, `docs/process_flow.png`,
`docs/ASSUMPTIONS.md`, `results/vsm_hand_calc.csv`.

<!-- BEGIN:hand_calc -->
| Step | Process | Dept | Source | Min/EVA | Min/3 EVA | Ops | Labour min/EVA | EVA/shift | EVA/week | Resource util. @ demand |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Engineering drawing release | engineering | assumed | - | 1 d | - | - | - | - | - |
| 2 | Procure sheet metal (cut to size) | outsourced | assumed | - | 4 d | - | - | - | - | - |
| 2 | Procure tubing | outsourced | assumed | - | 8.75 d | - | - | - | - | - |
| 3 | Fin Press (setup + punching) | evaporator | time study | 76.2 | 228.6 | 1 | 76.2 | 6.30 | 31.50 | 22.0 % |
| 5 | Boxing (modules + end panels) | evaporator | assumed | 100.0 | 300.0 | 1 | 100.0 | 4.80 | 24.00 | 22.0 % |
| 6 | Trim Tubes | evaporator | assumed | 40.0 | 120.0 | 1 | 40.0 | 12.00 | 60.00 | 5.0 % |
| 6 | Weld Hairpins | evaporator | time study | 216.0 | 648.0 | 1 | 216.0 | 2.22 | 11.11 | 27.0 % |
| 7 | Steeking | evaporator | estimate | 420.0 | 1,260.0 | 2 | 840.0 | 1.14 | 5.71 | 52.5 % **(BN)** |
| 8 | Weld Return Bends | evaporator | time study | 144.0 | 432.0 | 1 | 144.0 | 3.33 | 16.67 | 18.0 % |
| 9 | Hydraulic Expanding | evaporator | time study | 87.0 | 261.0 | 1 | 87.0 | 5.52 | 27.59 | 10.9 % |
| 10 | Prepare Headers | evaporator | assumed | 120.0 | 360.0 | 1 | 120.0 | 4.00 | 20.00 | 15.0 % |
| 10 | Header Welding | evaporator | time study | 384.0 | 1,152.0 | 1 | 384.0 | 1.25 | 6.25 | 48.0 % |
| 11 | Wash Bay | evaporator | assumed | 45.0 | 135.0 | 1 | 45.0 | 10.67 | 53.33 | 5.6 % |
| 12 | Pressure Test | evaporator | assumed | 90.0 | 270.0 | 1 | 90.0 | 5.33 | 26.67 | 11.2 % |
| 13 | Plenum: Press Brake | sheet_metal | assumed | 40.0 | 120.0 | 1 | 40.0 | 12.00 | 60.00 | 5.0 % |
| 13 | Plenum: Flat Welding | sheet_metal | assumed | 90.0 | 270.0 | 1 | 90.0 | 5.33 | 26.67 | 11.2 % |
| 13 | Plenum Assembly | sheet_metal | assumed | 60.0 | 180.0 | 1 | 60.0 | 8.00 | 40.00 | 13.1 % |
| 14 | Drip tray: external bend & punch | outsourced | assumed | - | 5 d | - | - | - | - | - |
| 14 | Drip Tray: Weld | sheet_metal | assumed | 100.0 | 300.0 | 1 | 100.0 | 4.80 | 24.00 | 12.5 % |
| 14 | Drip Tray Assembly | sheet_metal | assumed | 45.0 | 135.0 | 1 | 45.0 | 10.67 | 53.33 | 13.1 % |
| 15 | Powder coating / galvanising | outsourced | assumed | - | 3 d | - | - | - | - | - |
| 15 | Complete Assembly | assembly | assumed | 150.0 | 450.0 | 2 | 300.0 | 3.20 | 16.00 | 18.8 % |
<!-- END:hand_calc -->

---

## Phase 2: Analytical model

**Objective.** Implement and test the equations (fin-press OEE A1-A9, weld
metrics B, system C), the deterministic capacity and bottleneck calculation,
and the Kingman cross-check.

**What was done.** `equations.py` contains `fin_press` (A1-A7),
`calibrate_good_fins` (A8), `station_metrics` and `crew_elapsed` (B), and
`resource_loads`, `bottleneck`, `kingman_wq`, `littles_law_wip` and `va_ratio`
(C). It also has an **independent critical-path function**
(`deterministic_lead_time`) that does not use SimPy. 20 unit tests were added.

<!-- BEGIN:fin_press -->
| Case | S (min) | P | Q | MTBF/MTTR (min) | t_r (min) | T_job (min/3 EVA) | OEE |
|---|---|---|---|---|---|---|---|
| baseline (calibrated) | 30 | 0.95 | 0.98 | 270/30 | 5 | 228.6 | 70.0 % |
| SMED only: setup -40% | 18 | 0.95 | 0.98 | 270/30 | 5 | 216.6 | 73.9 % |
| cap: setup -40%, A_u = P = 1 | 18 | 1 | 0.98 | 270/0 | 5 | 188.9 | 84.7 % |
| S4 package (SMED + TPM + quick reel change) | 18 | 0.985 | 0.99 | 540/10 | 2 | 188.1 | 85.0 % |
<!-- END:fin_press -->

<!-- BEGIN:weld_metrics -->
| Station | t_op (min) | ops/min | ops/h | n_ops/coil | min/coil | min per 3 EVA | Operators | EVA/shift | Util. @ 3/wk |
|---|---|---|---|---|---|---|---|---|---|
| Weld Hairpins | 4 | 0.250 | 15.0 | 54 | 216 | 648 (10.8 h) | 1 | 2.22 | 27.0 % |
| Weld Return Bends | 4 | 0.250 | 15.0 | 36 | 144 | 432 (7.2 h) | 1 | 3.33 | 18.0 % |
| Hydraulic Expanding | 3 | 0.333 | 20.0 | 24 | 87 | 261 (4.3 h) | 1 | 5.52 | 10.9 % |
| Header Welding | 8 | 0.125 | 7.5 | 48 | 384 | 1152 (19.2 h) | 1 | 1.25 | 48.0 % |
<!-- END:weld_metrics -->

**Problems and fixes**
- **229 vs 228.6 min.** With the calibrated parameters, equations A1-A5 give
  T_job = 228.6 min and OEE = 69.99 %. The whiteboard's 229 min is the rounded
  value. Every table uses the exact value, and the test asserts |T_job - 229| < 0.5.
- **The S4 target of 85 % OEE cannot be reached with "SMED and fewer stops"
  alone.** With setup -40 %, OEE only reaches 73.9 %. With S = 18 min, Q =
  0.98 and a 5-min reel change, OEE is capped at 84.7 % even at A_u = P = 1.
  S4 is therefore defined as a package (A23) that reaches 85.0 %.
- ruff's SIM300 rule flagged `r.OEE == approx(...)` as a "Yoda condition",
  because the upper-case attribute looks like a constant. The rule is disabled.

**Verification evidence.** `tests/test_equations.py`: whiteboard
reproduction, calibration, the S4 options, metrics 1-3 for each weld station,
the header-welding figures in the brief, crew efficiency, the steeking capacity
of 5.71 EVA/week, the bottleneck ranking and shift, Kingman = M/M/1 and
Pollaczek-Khinchine, Little's law, the critical path and time scaling.

---

## Phase 3: Input analysis

**Objective.** Generate synthetic time-study data and fit candidate distributions.

**What was done.** `data/time_study_samples.csv` contains 40 observations for
each of 17 operations (seed 3131). Lognormal, gamma and Weibull were fitted by
MLE and screened with KS and AIC. Histogram and Q-Q figures were drawn for the
fin press, steeking, header welding and hairpins.

<!-- BEGIN:input_analysis -->
| Operation | n | Mean (min) [95 % CI] | CV | Lowest AIC | Lognormal ΔAIC | KS p (selected) | Selected |
|---|---|---|---|---|---|---|---|
| Fin press job (3 EVA) | 40 | 229.2 [221.9, 236.4] | 0.099 | gamma | 0.11 | 0.99 | lognormal |
| Boxing (modules + end panels) | 40 | 101.8 [97.1, 106.4] | 0.143 | lognormal | 0.00 | 0.62 | lognormal |
| Trim Tubes | 40 | 39.0 [37.2, 40.7] | 0.140 | lognormal | 0.00 | 0.72 | lognormal |
| Weld Hairpins | 40 | 212.3 [205.2, 219.5] | 0.105 | lognormal | 0.00 | 0.74 | lognormal |
| Steeking | 40 | 419.5 [393.6, 445.4] | 0.193 | weibull | 2.23 | 0.68 | weibull |
| Weld Return Bends | 40 | 147.7 [140.8, 154.6] | 0.146 | lognormal | 0.00 | 0.12 | lognormal |
| Hydraulic Expanding | 40 | 86.0 [82.9, 89.0] | 0.112 | lognormal | 0.00 | 0.97 | lognormal |
| Prepare Headers | 40 | 117.3 [111.9, 122.6] | 0.143 | gamma | 0.13 | 0.68 | lognormal |
| Header Welding | 40 | 380.4 [361.5, 399.3] | 0.156 | gamma | 0.95 | 0.85 | lognormal |
| Wash Bay | 40 | 45.0 [42.9, 47.2] | 0.148 | lognormal | 0.00 | 0.79 | lognormal |
| Pressure Test | 40 | 91.1 [86.1, 96.1] | 0.172 | lognormal | 0.00 | 0.47 | lognormal |
| Plenum: Press Brake | 40 | 38.2 [36.5, 39.9] | 0.140 | gamma | 0.45 | 0.35 | lognormal |
| Plenum: Flat Welding | 40 | 88.0 [83.7, 92.3] | 0.153 | gamma | 1.14 | 0.73 | lognormal |
| Plenum Assembly | 40 | 61.2 [57.5, 64.9] | 0.190 | gamma | 0.21 | 0.95 | lognormal |
| Drip Tray: Weld | 40 | 102.0 [96.3, 107.8] | 0.176 | lognormal | 0.00 | 0.45 | lognormal |
| Drip Tray Assembly | 40 | 43.9 [41.6, 46.2] | 0.165 | lognormal | 0.00 | 0.67 | lognormal |
| Complete Assembly | 40 | 149.6 [143.6, 155.7] | 0.126 | weibull | 1.79 | 0.78 | lognormal |
<!-- END:input_analysis -->

**Problem and decision.** The selection rule (lognormal unless another family
beats it by more than 2 AIC units) picks the **Weibull for steeking**, because
the lognormal ΔAIC is 2.23. The samples were drawn from a lognormal, so this is
sampling noise at n = 40, but overriding a documented rule after seeing the
result would be bad practice. Instead:
1. The model supports per-operation families through `variate_from_z`. Gamma
   and Weibull use the inverse CDF of Φ(z), which keeps common random numbers
   when the family changes.
2. A robustness run in Phase 7 swaps steeking back to lognormal. The paired
   difference is not significant for any KPI
   (`results/distribution_robustness.csv`).

---

## Phase 4: Core DES

**Objective.** Build a SimPy network with shared operators, parallel branches,
joins, outsourcing, rework, push/CONWIP release, a calendar, and full
instrumentation.

**What was done.** `resources.py` contains `TimedResource` (state times by
activity, clipped to the window, and queue times), `Gate` (transfer batches)
and `TimeAverage`. `model.py` contains `EvaporatorModel`. Each order runs as
SimPy processes: engineering → procurement → fin press (setup, NegBin scrap,
stops on the run-time clock, reel changes) → tube, header, plenum and drip-tray
branches → joins → coil route with the test-and-rework loop → coating →
complete assembly. Per-EVA timestamps and per-stage WIP are recorded.

**Decisions and why**
- *Each order pre-draws all of its random numbers* (A26). The fin press keeps
  its own stream, because its draw count depends on scrap.
- In *deterministic mode*, the fin press uses the analytical T_eva, split into
  busy, down and changeover time. Its job time and state shares then equal the
  hand calculation exactly.

**Problems and fixes**
- The queue time at a station includes the time an EVA waits for the other
  EVA of its own lot (TB = 3). For example, the deterministic steeking "wait"
  averages 420 min. This is correct behaviour for a lot-based process, so it is
  documented rather than hidden. The Kingman check uses lot-level queues.
- An unused placeholder event (`drip_out`) was removed in review.

**Verification evidence (first runs).** Deterministic order lead time = 10,488
min with the brief's 8-day tubing lead time, equal to the hand calculation.
Utilisations of 52.5 % (steeking), 48.0 % (header) and 22.0 % (fin press /
boxing) also equal it. A stochastic replication takes about 0.1 s.

---

## Phase 5: Metrics and Monte Carlo runner

**Objective.** KPIs, parallel replications, two-level uncertainty, convergence.

**What was done.** `metrics.py`: throughput, attainment, weekly compliance,
order lead time (mean/P50/P90/P95), on-time delivery, WIP by stage,
Little's-law WIP, FPY, VA ratio, bottleneck by active share and by queue,
Student-t CIs, paired-t, and random-effects variance decomposition.
`runner.py`: SeedSequence keys, a persistent spawn process pool, and optional
θ per replication. The pipeline runs the baseline, convergence, the nested
two-level design, the full two-level run and the steeking cases.

<!-- BEGIN:convergence -->
| Metric | Target ± (% of mean) | Replications required | Achieved |
|---|---|---|---|
| lt_mean_days | 0.5 % | 56 | ±0.21 % (300 reps) |
| lt_mean_days | 1 % | 16 | ±0.21 % (300 reps) |
| lt_mean_days | 2 % | 6 | ±0.21 % (300 reps) |
| lt_p90_days | 0.5 % | 192 | ±0.40 % (300 reps) |
| lt_p90_days | 1 % | 50 | ±0.40 % (300 reps) |
| lt_p90_days | 2 % | 15 | ±0.40 % (300 reps) |
| throughput_eva_week | 0.5 % | 213 | ±0.42 % (300 reps) |
| throughput_eva_week | 1 % | 55 | ±0.42 % (300 reps) |
| throughput_eva_week | 2 % | 16 | ±0.42 % (300 reps) |
<!-- END:convergence -->

**Problems and fixes**
- *Fin-press utilisation looked 2.3 pp below the hand calculation.* The hand
  calculation counts setup and stop time, while the busy share only counts
  punching. The fair comparison is the **active share** (busy + changeover +
  down). With it, every resource agrees within 0.2 pp.
- *Little's law failed per replication on a 20-week test window* (up to 6 %
  off), because orders in flight at the window edges take about 4.5 weeks. The
  test now uses the 52-week window, a tolerance of 6 % per replication and 1.5 %
  on the mean. On the baseline the two estimates agree to 0.04 %.

---

## Phase 6: Verification and validation

**Objective.** Show that the model is built right (verification) and is the
right model (validation).

**Verification**: 48 tests, including:

<!-- BEGIN:deterministic -->
| Case | Quantity | Hand calc | Simulated (min-max) | Exact |
|---|---|---|---|---|
| baseline (transfer batch 3) | order lead time (min) | 10848.00 | 10848.00 | yes |
| baseline (transfer batch 3) | utilisation: steeking_crew | 0.5250 | 0.5250 | yes |
| baseline (transfer batch 3) | utilisation: header_welder | 0.4800 | 0.4800 | yes |
| baseline (transfer batch 3) | utilisation: fin_press_operator | 0.2203 | 0.2203 | yes |
| baseline (transfer batch 3) | EVA per week | 3.0000 | 3.0000 | yes |
| baseline (transfer batch 3) | fin press job (min) | 228.61 | 228.61 - 228.61 | yes |
| transfer batch 1 | order lead time (min) | 8536.00 | 8536.00 | yes |

_19 of 19 checked quantities match exactly (all 15 resource utilisations included). Source: `results/deterministic_check.csv`._
<!-- END:deterministic -->

- The stochastic fin-press mean over 1,000+ jobs is within 1 % of T_job (A9).
- Little's law, conservation of EVA (arrived = completed + in system), and
  joins never starting before all their inputs.
- Transfer batches move together, the CONWIP limit is never exceeded, the
  rework loop works, runs are reproducible and parallel equals serial, CRN
  correlation is positive, and the bottleneck shifts with a third steeker.
- Input-uncertainty sampling, and an M/G/1 Kingman/Pollaczek-Khinchine bench
  (within 6 %).

**Kingman in the network.** Kingman using the *measured* lot interarrival SCV
overstates the simulated steeking queue, and Kingman using the *release* SCV
understates it. The simulation lies between the two at every demand level.
Arrivals deep in the network are order releases plus independent delays, so
the gaps are negatively correlated and not renewal (A36). Header welding gets
arrivals already spaced by the steeking bottleneck, and the simulated queue
there is far below Kingman, as theory predicts for a regulated stream.

<!-- BEGIN:kingman -->
| Demand | Station | rho (sim) | ca² measured / release | cs² (lot) | Wq sim (h) | Kingman (h): release ca² / measured ca² | Bracketed |
|---|---|---|---|---|---|---|---|
| 3 | steeking | 0.525 | 0.37 / 0.0625 | 0.0152 | 2.8 | 0.9 / 4.4 | yes |
| 3 | header_welding | 0.486 | 0.28 / 0.0625 | 0.0091 | 0.3 | 0.6 / 2.6 | no |
| 4 | steeking | 0.698 | 0.41 / 0.0625 | 0.0153 | 5.9 | 1.9 / 10.3 | yes |
| 4 | header_welding | 0.647 | 0.23 / 0.0625 | 0.0098 | 0.5 | 1.3 / 4.2 | no |
| 5 | steeking | 0.872 | 0.41 / 0.0625 | 0.0150 | 12.9 | 5.5 / 30.1 | yes |
| 5 | header_welding | 0.805 | 0.11 / 0.0625 | 0.0097 | 0.8 | 2.9 / 4.8 | no |
| 5.5 | steeking | 0.956 | 0.40 / 0.0625 | 0.0151 | 26.7 | 17.4 / 93.3 | yes |
| 5.5 | header_welding | 0.881 | 0.05 / 0.0625 | 0.0091 | 1.2 | 5.1 / 4.2 | no |
<!-- END:kingman -->

**Validation.** With the brief's 8-day tubing lead time, the model was 7.9 %
below the observed mean order lead time (p = 0.02), so it failed. The
investigation found that the hidden "real" system has a 11.8 % longer tubing
lead time, which explains +4.1 % in expectation, and that the 26-week
observation sits about 1.6 SD above even the real system's mean (sampling
noise). A **minimum-change calibration** of the assumed tubing lead time (A35)
then gave:

<!-- BEGIN:calibration -->
| Tubing mean (d) | Sim. LT (d) | Error vs observed | PI p | Passes | Note |
|---|---|---|---|---|---|
| 8.00 | 22.35 | -7.94 % | 0.020 | no | brief value |
| 8.25 | 22.62 | -6.85 % | 0.020 | no |  |
| 8.50 | 22.88 | -5.79 % | 0.033 | no |  |
| 8.75 | 23.14 | -4.70 % | 0.093 | yes | **selected (minimum change)** |
| 9.00 | 23.41 | -3.61 % | 0.233 | yes |  |
| 9.25 | 23.67 | -2.54 % | 0.339 | yes |  |
| 9.75 | 24.19 | -0.40 % | 0.837 | yes | best fit |
<!-- END:calibration -->

<!-- BEGIN:validation -->
| Measure | Observed (26 wk) | Simulated | Error | Sim. 95 % PI | PI p | Welch p | Verdict |
|---|---|---|---|---|---|---|---|
| Mean weekly output (EVA/week) | 2.88 | 2.98 | +3.20 % | [2.65, 3.35] | 0.784 | 0.514 | valid |
| Mean order lead time (working days) | 24.28 | 23.14 | -4.70 % | [21.93, 24.45] | 0.093 | 0.104 | valid |
<!-- END:validation -->

The best-fit value (9.75 d) would have overfit the noise. The true perturbed
value is 8.94 d, so the minimum-change value (8.75 d) is the closer of the two.

---

## Phase 7: Scenarios, demand sweep and sensitivity

**Objective.** Quantify each improvement at 3 and 5 EVA/week with paired CIs,
draw the lead-time hockey stick, and rank the input drivers.

**What was done.** S0-S6 from the brief plus S7 (the recommendation), at both
demands with CRN. A demand sweep over 3-6 EVA/week for five scenarios.
One-at-a-time sensitivity over 16 operations, fin-press setup/MTBF/MTTR, 5
lead times and the steeking crew. A family-robustness run, and the bottleneck
shift under input uncertainty.

<!-- BEGIN:scenarios -->
| Demand | Scenario | TH (EVA/wk) | LT mean (d) | ΔLT vs S0 [95 % CI] | ΔLT % | p | LT P95 (d) | On-time | Steeking util. | Header util. | Bottleneck |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | **S0** Baseline | 2.99 | 23.12 | - | - | - | 28.2 | 97.2 % | 52 % | 48 % | Steeking (100 %) |
| 3 | **S1** 3rd steeking operator | 2.99 | 22.47 | -0.66 d [-0.66, -0.65] | -2.8 % | < 0.001 | 27.6 | 98.0 % | 41 % | 48 % | Header welding (100 %) |
| 3 | **S2** Steeking standard work / fixtures | 2.99 | 22.51 | -0.61 d [-0.62, -0.61] | -2.7 % | < 0.001 | 27.6 | 98.0 % | 42 % | 48 % | Header welding (100 %) |
| 3 | **S3** 2nd header-welding station | 2.99 | 22.22 | -0.91 d [-0.91, -0.90] | -3.9 % | < 0.001 | 27.3 | 98.2 % | 52 % | 24 % | Steeking (100 %) |
| 3 | **S4** Fin press OEE 70% -> 85% | 2.99 | 23.12 | +0.00 d [0.00, 0.00] | +0.0 % | 1.000 | 28.2 | 97.2 % | 52 % | 48 % | Steeking (100 %) |
| 3 | **S5** One-piece flow (transfer batch 1) | 2.99 | 18.64 | -4.48 d [-4.50, -4.46] | -19.4 % | < 0.001 | 23.8 | 99.7 % | 52 % | 48 % | Steeking (100 %) |
| 3 | **S6** Combined: S1 + S3 + CONWIP | 2.99 | 21.49 | -1.63 d [-1.64, -1.62] | -7.0 % | < 0.001 | 26.5 | 98.9 % | 41 % | 24 % | Steeking (100 %) |
| 3 | **S7** Recommended: S6 + one-piece flow | 2.99 | 17.88 | -5.24 d [-5.27, -5.22] | -22.7 % | < 0.001 | 22.9 | 99.8 % | 41 % | 24 % | Steeking (100 %) |
| 5 | **S0** Baseline | 4.98 | 24.72 | - | - | - | 30.1 | 94.2 % | 87 % | 80 % | Steeking (100 %) |
| 5 | **S1** 3rd steeking operator | 4.98 | 23.50 | -1.22 d [-1.25, -1.20] | -5.0 % | < 0.001 | 28.8 | 96.7 % | 68 % | 80 % | Header welding (100 %) |
| 5 | **S2** Steeking standard work / fixtures | 4.98 | 23.55 | -1.18 d [-1.20, -1.15] | -4.8 % | < 0.001 | 28.8 | 96.7 % | 70 % | 80 % | Header welding (100 %) |
| 5 | **S3** 2nd header-welding station | 4.98 | 23.73 | -0.99 d [-1.00, -0.99] | -4.0 % | < 0.001 | 29.1 | 96.2 % | 87 % | 40 % | Steeking (100 %) |
| 5 | **S4** Fin press OEE 70% -> 85% | 4.98 | 24.72 | +0.00 d [0.00, 0.00] | +0.0 % | 1.000 | 30.1 | 94.2 % | 87 % | 80 % | Steeking (100 %) |
| 5 | **S5** One-piece flow (transfer batch 1) | 4.98 | 20.21 | -4.51 d [-4.53, -4.49] | -18.2 % | < 0.001 | 25.5 | 99.2 % | 87 % | 80 % | Steeking (100 %) |
| 5 | **S6** Combined: S1 + S3 + CONWIP | 4.98 | 22.58 | -2.14 d [-2.16, -2.12] | -8.7 % | < 0.001 | 27.8 | 98.0 % | 68 % | 40 % | Steeking (100 %) |
| 5 | **S7** Recommended: S6 + one-piece flow | 4.98 | 18.45 | -6.28 d [-6.31, -6.24] | -25.4 % | < 0.001 | 23.6 | 99.8 % | 68 % | 40 % | Steeking (100 %) |
<!-- END:scenarios -->

**Problems and fixes**
- **CONWIP gate.** The first design took the card at drawing release, so cards
  sat idle through the 8.75-day tubing wait and the limit capped
  material-waiting orders, not WIP on the floor. The card is now taken when
  tubing is kitted (A13b). The push behaviour did not change (the regenerated
  baseline was identical).
- **CONWIP limit.** A pilot chose 3 as the smallest limit that keeps
  throughput at 5 EVA/week (A37). The sweep later showed that a fixed limit of
  3 restricts S6 at 6 EVA/week, so the limit has to grow with demand.
- **S4 has exactly zero effect** (difference 0.000, p = 1). This is a finding,
  not a bug. The fin press finishes within a day of drawing release, while
  tubing takes 8.75 days, so the fin press never lies on the critical path and
  improving its OEE cannot shorten lead time.
- **Unstable-run flag.** The first heuristic (end-of-run WIP > 2.5 × baseline)
  missed steeking crew 1 at 3 EVA/week, which is unstable because capacity 2.86
  is below demand 3. It was replaced by the analytic test (any resource load ≥ 100 %).
- **The bottleneck never shifted under process variability alone** (100 %
  steeking in S0). The 4.5 pp utilisation gap between steeking and header
  welding is far larger than the replication noise. It *does* shift under input
  uncertainty: header welding is the bottleneck in about 5 % of plausible
  steeking worlds, those below 386.5 min/EVA (A41).

<!-- BEGIN:sensitivity -->
| Demand | Factor | Low (−10 % / crew −1) | High (+10 % / crew +1) |
|---|---|---|---|
| 3 | Steeking crew (2 ± 1) | +12.41 d (unstable) | -0.65 d |
| 3 | Procure tubing lead time | -0.92 d | +0.91 d |
| 3 | Steeking time | -0.32 d | +0.36 d |
| 3 | Powder coating / galvanising lead time | -0.30 d | +0.30 d |
| 3 | Header Welding time | -0.26 d | +0.29 d |
| 3 | Weld Hairpins time | -0.13 d | +0.14 d |
| 5 | Steeking crew (2 ± 1) | +62.18 d (unstable) | -1.21 d |
| 5 | Steeking time | -0.77 d | +2.07 d |
| 5 | Procure tubing lead time | -0.98 d | +0.96 d |
| 5 | Header Welding time | -0.32 d | +0.57 d |
| 5 | Powder coating / galvanising lead time | -0.31 d | +0.30 d |
| 5 | Weld Hairpins time | -0.14 d | +0.14 d |

_Paired change in mean order lead time against the baseline at the same demand (CRN, 100 replications). Source: `results/sensitivity_oat.csv`._
<!-- END:sensitivity -->

---

## Phase 8: VSM visuals

**Objective.** Draw current-state and future-state value stream maps of the
network, colour-coded by department, with the outsourced legs shown.

**What was done.** `vsm.py` draws a feeder row, the coil line, the sheet-metal
row and the outsourced legs. Each process has a data box (CT, operators,
OEE/uptime, FPY, utilisation, queue time). The maps include Little's-law
inventory triangles, push vs one-piece-flow arrows, kaizen bursts, and a
timeline ladder along the critical coil path. The current state is S0 at
3 EVA/week and the future state is S7 at 5 EVA/week. The maps are drawn from
300-replication runs, so they match `scenario_summary.csv` exactly.

<!-- BEGIN:vsm_summary -->
| VSM measure | S0 baseline @ 3/wk | S0 @ 5 @ 5/wk | S7 Recommended: S6 + one-piece flow @ 5/wk |
|---|---|---|---|
| Throughput (EVA/week) | 2.99 | 4.98 | 4.98 |
| Order lead time (days) | 23.1 | 24.7 | 18.4 |
| Order lead time P95 (days) | 28.2 | 30.1 | 23.6 |
| Value-added time (min/EVA) | 2207 | 2207 | 2116 |
| VA ratio (%) | 20.2 | 18.8 | 25.3 |
| WIP (EVA) | 13.7 | 24.4 | 17.4 |
| Queue before steeking (h) | 9.6 | 20.2 | 5.9 |
| On-time (%) | 97.2 | 94.2 | 99.8 |
<!-- END:vsm_summary -->

**Problems and fixes.** The first draft had the legend over the supplier icon,
dotted tubing arcs crossing the fin-press box, arrows starting in mid-air and
labels overflowing their boxes. These were fixed with text wrapping, a text
note instead of crossing arcs, and fixed anchor points. The ladder sum is
shorter than the order lead time because joins and transfer-batch waits
outside the coil path are not on the ladder. This is stated on the map.

---

## Phase 9: Dashboard

**Objective.** Interactive what-if analysis.

**What was done.** `app/dashboard.py` (Streamlit). The inputs are scenario,
demand, transfer batch, steeking crew, header stations, release rule and
CONWIP limit, time scale, input uncertainty, and an editable operation table.
The outputs are KPI tiles with paired deltas against S0, and tabs for lead
time, resource states, bottleneck, the demand curve and the scenario
comparison. It is tested with `AppTest` and was checked in a headless browser.

**Problems and fixes.** KPI tiles were truncated ("3.02 EV…", "Steekin…"), so
the units moved into the tile titles and resource names are shortened.

---

## Phase 10: Documentation and polish

**What was done.** README, MODEL_DESCRIPTION, OPERATING_PROCEDURES, this
file, the executed notebook, the Makefile, and the CI workflows (project-level
and repository root). `evapsim.report` writes every results table in the
README and docs from `results/*.csv`.

**Problems and fixes**
- **A circular validation bug, found during the final regeneration.**
  Re-running `make data` after the calibration changed
  `observed_weekly_output.csv`, and the calibration then "needed" 9.75 days.
  The generator built the hidden real system by perturbing the *current*
  config, which already held the calibrated 8.75 days, so calibrating the model
  moved the observations. The real system is now built from the brief's
  nominal values (`brief_mean_days`). The regenerated file is byte-identical to
  the original, and a regression test
  (`test_observed_data_independent_of_calibration`) prevents a repeat.
- After the Phase 7 change to the CONWIP gate, `baseline_wip_by_stage.csv`
  still showed the old stage name `waiting_card`. Every result was regenerated
  in one pipeline run before the documentation was written.
- `make all` was run from a fresh clone (see the final section of the README
  for the runtime), and the regenerated CSVs were compared with the committed
  ones.
