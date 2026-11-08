# Standard operating procedures: evaporator-line-des (v2)

| Item | Value |
|---|---|
| Document | SOP-EVAPSIM-002 |
| Applies to | evapsim 2.0.0, `meta.config_version` 2.0.0 |
| Data status | **Illustrative and anonymised** ("the Company"). This is not measured company data |

---

## 1. Purpose and scope

1.1 This SOP explains how to run, change, re-validate and read the
discrete-event simulation (DES) of the evaporator production system. It covers
the evaporator line and its sheet-metal and outsourced feeder flows.

1.2 It covers the command-line pipeline, the YAML inputs, the scenario file,
the Streamlit dashboard, the result files, and how to replace the illustrative
inputs with real time-study data. For changes to the model code, see
`docs/MODEL_DESCRIPTION.md`.

1.3 Users: industrial and production engineers who are evaluating staffing,
equipment, batching, release rules or demand growth.

## 2. Prerequisites

2.1 You need Python 3.11 or newer, git and GNU make. On Windows, run the
`python -m evapsim <step>` commands listed in the Makefile instead of `make`.
Allow about 400 MB of disk space for the dependencies.

2.2 Install:

```bash
git clone <repository-url>
cd <repository>/evaporator-line-des
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
make setup
make lint test                                        # must be green before any run
```

2.3 Worker processes default to all CPU cores. Set `EVAPSIM_WORKERS=2` or pass
`--workers 2` to use fewer.

### Pre-run checklist

- [ ] `make lint test` is green.
- [ ] `config/line_parameters.yaml` is edited as intended, and `meta.config_version` has been increased (§11).
- [ ] Every edited input still has the right `source` tag (`time study`, `estimate` or `assumed`).
- [ ] `time_scale_factor` is what you intend (1.0 = values as entered).
- [ ] `simulation.base_seed` is unchanged, unless a new random sample is wanted on purpose.
- [ ] The mode is chosen: **quick** (30 replications, `results/quick/`) for exploration, **full** (300) for reporting.
- [ ] Demand is below the steeking capacity, or you understand that the run is unstable (lead time then grows with the horizon).

## 3. Running the baseline

3.1 Command: `make baseline` (full) or `make baseline QUICK=1`.

3.2 What runs:
1. `handcalc`: hand-calculated VSM, resource loads, critical path, the deterministic-simulation check and the process-flow figure.
2. `analytic`: fin-press calibration, OEE options, weld-station metrics, analytic Kingman.
3. `input`: distribution fitting of the time-study samples.
4. `baseline`: 300 replications, plus convergence.
5. `validate`: comparison with `data/observed_weekly_output.csv`, the calibration grid and the Kingman bracket check.
6. `uncertainty`: two-level Monte Carlo, variance decomposition, the 6/7/16/20 h steeking cases, and the bottleneck shift.

3.3 Runtime: one replication takes about 0.1 s, so 300 replications take about
10-15 s on 4 cores. The whole `make baseline` takes a few minutes, mostly in
validation (calibration grid) and the two-level uncertainty runs. The complete
pipeline (baseline, scenarios, sweep, sensitivity) took about 15 minutes on
4 cores.

3.4 Main outputs: `results/vsm_hand_calc.csv`, `resource_loads.csv`,
`deterministic_check.csv`, `baseline_kpis.csv`, `baseline_resources.csv`,
`baseline_stations.csv` (queue time per station),
`baseline_bottleneck_frequency.csv`, `baseline_wip_by_stage.csv`,
`convergence*.csv`, `validation_summary.csv`, `calibration_grid.csv`,
`kingman_check.csv`, `variance_decomposition.csv` and `steeking_cases.csv`,
plus the figures in `results/figures/`.

## 4. Editing inputs (`config/line_parameters.yaml`)

4.1 **Operation time**: change `mean_min`, or `t_op_min` / `n_ops` /
`handling_min` for weld stations, and `cv`. Update `source`.

4.2 **Change a crew** (for example steeking): set `resources.steeking_crew.crew`.
The elapsed time is recalculated as labour / (crew × η(crew)). Adjust
`crew_efficiency` if better efficiency data exist.

4.3 **Add parallel stations**: set `resources.<id>.servers`, for example
`header_welder.servers: 2`.

4.4 **Batch sizes**: `orders.lot_size` (EVA per work order) and
`orders.transfer_batch` (1 ... lot size).

4.5 **Shift pattern**: `calendar.minutes_per_day` (productive minutes) and
`calendar.days_per_week`. Lead times in working days follow automatically.

4.6 **Scale all process times** (anonymisation or what-if): set
`time_scale_factor`, for example 0.8. Process times, fin-press setup, reload,
MTTR and MTBF are scaled. Calendar lead times are not (A20).

4.7 **Add a station**:
1. Add an operation block under `operations:` with `step`, `label`,
   `department` (engineering | evaporator | sheet_metal | outsourced |
   assembly), `resource`, the time fields, `cv` and `source`.
2. Add the resource under `resources:`, or point to an existing one to share it.
3. Insert the operation into the routing in `src/evapsim/model.py`
   (`EvaporatorModel._coil` for the coil route, or the branch it belongs to)
   and append it to `OPS`.
4. Add it to `COIL_PATH`, `FEEDERS` or `SHEET` in `src/evapsim/vsm.py`, and
   add a row to the critical-path function in `equations.py` if it is on the
   path.
5. Run `make test`. The deterministic tests (`test_deterministic_*`) must
   still pass, which proves the hand calculation and the DES agree.

4.8 **Wash/test order and coating**: `flags.wash_before_test`,
`flags.include_outsourced_coating`.

4.9 **Verification mode**: `simulation.deterministic: true`. This removes all
variability, stops, scrap and test failures, so the run reproduces the hand
calculation exactly.

## 5. Defining a new scenario (`config/scenarios.yaml`)

5.1 Add a block:

```yaml
  S8:
    name: "Second steeking fixture"
    description: "Two steeking fixtures, each with a 2-person crew."
    extends: [S3]                       # optional: start from another scenario
    overrides:
      resources:
        steeking_crew: {servers: 2}
      operations:
        weld_hairpins: {t_op_min: {scale: 0.9}}
      lead_times:
        procurement_tubing: {mean_days: {add: -2}}
```

5.2 Operators are `{scale: x}` and `{add: x}`. Integer fields (servers, crew,
batch sizes, CONWIP limit) are rounded.

5.3 Run `make scenarios`. Every scenario is simulated at each demand in
`demand.scenario_eva_per_week`, with the same seeds as S0. Paired differences
against S0 at the same demand go to `results/scenario_paired_differences.csv`.

## 6. Running the demand sweep and sensitivity

6.1 **Demand sweep**: `make sweep`. It covers `demand.sweep_eva_per_week` for
S0, S1, S3, S6 and S7 (`SWEEP_SCENARIOS` in `sensitivity.py`), and writes
`results/demand_sweep.csv` and `figures/demand_curve.png`.

6.2 **Sensitivity**: `make sensitivity`. It changes each operation time, the
fin-press setup, MTBF and MTTR, each lead time (±10 %) and the steeking crew
(±1), at each scenario demand. It writes `results/sensitivity_oat.csv`,
`figures/sensitivity_tornado.png` and `results/distribution_robustness.csv`.
It takes a few minutes on 4 cores.

6.3 **Two-level uncertainty**: `python -m evapsim uncertainty`. Edit
`input_uncertainty` to change the triangular range, the nested design or the
steeking cases.

## 7. Using the dashboard

7.1 `make dashboard` (or `streamlit run app/dashboard.py`) opens it at
http://localhost:8501.

7.2 Sidebar: scenario, demand, transfer batch, steeking crew, header stations,
release rule and CONWIP limit, `time_scale_factor`, input-uncertainty toggle,
replications, measured weeks, workers, and whether to compare with S0.

7.3 In the main panel you can edit operation times or CVs in the table. The
caption shows takt and steeking capacity, and a red banner warns when demand
exceeds capacity.

7.4 **Run simulation** shows KPI tiles (with the paired difference against S0
at the same demand, and the 95 % CI in the tooltip) and five tabs: lead-time
distribution, resource states, bottleneck, demand curve (committed sweep plus
this run as a star) and scenario comparison.

## 8. Reading the outputs

| Output | How to read it | What "good" looks like |
|---|---|---|
| Throughput | EVA/week. In a stable system it equals demand | equal to demand with a narrow CI. If it is lower, the system is unstable |
| Order lead time mean / P95 | working days from order arrival to the last EVA | P95 within the promised lead time (6 weeks = 30 d) |
| On-time delivery | share of orders completed by the due date | ≥ 95 % |
| WIP by stage | where EVA wait (engineering, awaiting material, prep, coil line, coating, final assembly) | WIP concentrated where it is planned (material, coating), not in front of the bottleneck |
| Utilisation and state bars | busy, changeover, down and starved share per resource | bottleneck ≤ 85 % for stable lead times. Fin press shows its OEE losses |
| Queue time per station | mean wait including waiting for the rest of the lot (TB = 3) | short waits at the bottleneck mean flow is balanced |
| Bottleneck frequency | share of replications in which each resource has the highest active share | 100 % at one resource = a clear constraint. A split = a shifting bottleneck |
| Paired differences | scenario - S0, 95 % CI, p | CI excludes 0 and the size of the effect matters in practice |
| Demand curve | lead time vs demand | flat region = spare capacity. The knee marks the useful capacity limit |
| Tornado | change in lead time for ±10 % on each factor | long bars show where better data or improvement pay off |
| Variance decomposition | input-uncertainty share of the variance | a high share means the input needs a time study before decisions are made |
| Validation | % error, prediction-interval p | \|error\| ≤ 5 % and p ≥ 0.05 |
| Kingman check | steeking queue bracketed by the two Kingman values | bracketed = queueing behaviour is plausible |

## 9. Replacing illustrative data with real data and recalibrating

9.1 **Time study**: record at least 30 observations per operation in the
format of `data/time_study_samples.csv` (`operation`, `observed_min`, `basis`).
Run `make input`. Enter the sample mean in `mean_min` (or `t_op_min`), the CV
in `cv` and the selected family in `distribution`. Set `source: time study`.

9.2 **Steeking first**: it is the bottleneck and the input with the largest
uncertainty (86 % of lead-time variance at 5 EVA/week comes from it). Time at
least 10 complete steeking cycles. Then narrow or remove
`input_uncertainty.steeking_triangular_min`.

9.3 **Observed performance**: replace `data/observed_weekly_output.csv`. Keep
the columns, and record lead times in *working* days from order arrival to the
last EVA complete. Use at least 20 weeks.

9.4 Run `make baseline` and read `validation_summary.csv`. If |error| > 5 % or
p < 0.05:
1. Check the calendar inputs first, especially supplier lead times, which
   dominate lead time.
2. Check `calibration_grid.csv`, and adopt the *minimum-change* value that
   passes (A35).
3. Record the change in `ASSUMPTIONS.md` and `BUILD_PHASES.md` (Phase 6) with
   its evidence.
4. Keep the last 4-6 weeks out of the calibration as a hold-out, and confirm
   the model on them.

9.5 Never tune a time-studied input to pass validation. Measure it again
instead.

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConfigError` listing problems | invalid value or unknown resource/department/source | fix the listed fields |
| `ModuleNotFoundError: evapsim` | package not installed | `make setup`, or `export PYTHONPATH=src` |
| Lead time keeps growing with the horizon, throughput < demand | demand ≥ bottleneck capacity (unstable) | reduce demand or add capacity; check the hand-calc resource loads |
| Results differ from the committed ones | config, seed or replication count changed | compare with `results/run_metadata.json` and `git diff config/`. Results are bit-for-bit reproducible for any number of workers |
| CI too wide | too few replications | use `convergence_required_replications.csv` |
| Scenario differences not significant | the effect is small, or the scenario changes a non-bottleneck (for example S4) | that may be the correct answer. Check the critical path |
| Warm-up looks too short | very high demand or large batches | increase `simulation.warmup_weeks` and plot weekly WIP |
| Dashboard hangs | process pool cannot start | set *Worker processes* to 1 |
| `make` not available | Windows | run the `python -m evapsim <step>` commands |

## 11. Version control practice

11.1 Every input change goes in its own commit with a conventional-commit
message, for example `feat(config): time-studied steeking 455 min`, and a
higher `meta.config_version`.

11.2 Re-run the affected steps, run `make report`, and commit the regenerated
`results/` together with the config change.

11.3 Generated tables in the README and docs (between `BEGIN`/`END` markers)
are never edited by hand.

11.4 New assumptions get a new ID in `ASSUMPTIONS.md`. Problems and fixes go in
`BUILD_PHASES.md`.

11.5 CI (ruff, pytest and a pipeline smoke test) must be green before merging.

### Results sign-off checklist

- [ ] CI is green. The run used full mode (300 replications, see `run_metadata.json`).
- [ ] `deterministic_check.csv` is all `exact_match = True`.
- [ ] The convergence half-width of mean lead time is ≤ 1 %.
- [ ] Validation: |error| ≤ 5 % and PI p ≥ 0.05, or a documented calibration.
- [ ] Little's law: `wip_total` ≈ `littles_wip` in `baseline_kpis.csv`.
- [ ] The bottleneck in the simulation agrees with the hand-calculated resource loads.
- [ ] Every scenario claim is backed by a paired 95 % CI, and unstable cases are labelled.
- [ ] Input-uncertainty findings are stated alongside the point estimates.
- [ ] `make report` was run, and the README and docs tables match `results/`.
- [ ] The illustrative-data disclaimer is present, with no real company names.
- [ ] Reviewer and date are recorded in the pull request.
