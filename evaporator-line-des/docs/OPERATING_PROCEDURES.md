# Standard operating procedures: evaporator-line-des

| Item | Value |
|---|---|
| Document | SOP-EVAPSIM-001 |
| Applies to | evapsim model v1.0.0, `config_version` 1.0.0 |
| Data status | **Fictional.** Every parameter and result is illustrative |

---

## 1. Purpose and scope

1.1 This SOP explains how to run, change, re-validate and read the
discrete-event simulation (DES) of the evaporator coil assembly line.

1.2 It covers the command-line pipeline (`make` / `python -m evapsim`), the
configuration files, the Streamlit dashboard and the result files. It does not
cover changing the model's source code. For that, see
`docs/MODEL_DESCRIPTION.md`.

1.3 Intended users: industrial and process engineers who want to test line
changes (buffers, SMED, maintenance, extra capacity, demand) before spending
money on them.

## 2. Prerequisites and setup

2.1 You need Python 3.11 or newer, `git`, `make` (on Windows, use the
`python -m evapsim ...` commands in the Makefile directly) and about 300 MB of
disk space for the dependencies.

2.2 Clone and install:

```bash
git clone <repository-url> evaporator-line-des
cd evaporator-line-des
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make setup                                          # pip install -r requirements.txt + -e .
```

2.3 Check the installation:

```bash
make lint test        # ruff must print "All checks passed!" and pytest must report 0 failures
```

2.4 Set the number of worker processes if needed. The default is all CPU
cores. To use fewer, set `EVAPSIM_WORKERS=2` or pass `--workers 2`.

### Pre-run checklist

- [ ] The virtual environment is active and `make test` passes.
- [ ] `config/line_parameters.yaml` has the intended values, and `config_version` has been increased if you changed anything (see §11).
- [ ] The product `mix` sums to 1.0, there are *(stations - 1)* buffer capacities, and station ids run 1..N with no gaps (the loader rejects anything else).
- [ ] `simulation.base_seed` is unchanged, unless you deliberately want a new random sample.
- [ ] You picked the mode: **quick** (50 replications, `results/quick/`) for exploring, **full** (500 replications, `results/`) for reporting.
- [ ] Enough time is available. A full `make all` takes about 20-25 minutes on 4 cores.

## 3. Running the baseline

3.1 Command:

```bash
make baseline            # full: 500 replications
make baseline QUICK=1    # quick: 50 replications -> results/quick/
```

3.2 What runs: input analysis (Phase 2), the static capacity check, the
baseline Monte Carlo run with the convergence study (Phases 4-5), and
validation against `data/observed_line_data.csv` (Phase 6).

3.3 Expected runtime: about 1 minute for 500 replications on 4 cores (about
0.5 s per replication per core). Quick mode takes under 15 seconds.

3.4 Expected output files:

| File | Content |
|---|---|
| `results/input_analysis.csv`, `figures/input_fit_S*.png` | Distribution fits per station |
| `results/static_capacity.csv` | Hand-calculated capacity per station |
| `results/baseline_kpis.csv` | KPI mean, SD and 95 % CI |
| `results/baseline_replications.csv` | One row of KPIs per replication |
| `results/baseline_stations.csv` | Station state shares, uptime, FPY, buffer levels |
| `results/baseline_daily_output.csv` | Output for every replication and day |
| `results/baseline_bottleneck_frequency.csv` | Bottleneck share per station (two methods) |
| `results/baseline_lead_time_histogram.csv`, `baseline_batch_lead_times.csv` | Lead-time distributions |
| `results/convergence.csv`, `convergence_required_replications.csv`, `figures/convergence.png` | Replication adequacy |
| `results/validation_*.csv`, `vsm_observed_vs_simulated.csv`, `figures/validation.png` | Validation evidence |
| `results/run_metadata.json` | Replications, seed and runtime of each step |

## 4. Changing inputs

All inputs are in `config/line_parameters.yaml`. The README section
*Inputs reference* lists every field with its units and valid range.

4.1 **Change a station parameter**: edit the field under `stations:`, for
example `ct_mean_s`, `ct_cv`, `servers`, `mtbf_min`/`mttr_min` (set both to
`null` for no breakdowns), `scrap_rate`, `changeover` and `changeover_min`.

4.2 **Change buffers**: edit `buffers.capacities`. The list needs one entry per
gap between stations, so 6 entries for 7 stations.

4.3 **Add a station**:
1. Insert a new block under `stations:` with the next `id`, and renumber the
   following stations so the ids stay 1..N in routing order.
2. Add one entry to `buffers.capacities`.
3. If the rework stations moved, update `rework.test_station` and
   `rework.rework_station`. The rework station must be upstream of the test
   station and must not be Station 1.
4. Fill in the station's `vsm:` block (operators, snapshot values).
5. Run `make test`. Tests that use hard-coded station numbers (for example the
   deterministic 78 s bottleneck) describe the *baseline* line and will need
   updating.

4.4 **Add a product**: append to `products:` with `name`, `mix` and
`ct_multiplier`, then rescale the other `mix` values so they sum to 1.0.

4.5 **Change the shift pattern**: set `shift.net_productive_minutes` (per
shift) and `shift.shifts_per_day`. Takt time is recalculated automatically.
Productive time is the only simulated time (A3), so breaks are left out.

4.6 **Change demand**: set `demand.units_per_day`. Throughput does not change,
because the line is saturated (A2), but takt compliance, attainment and days of
stock do.

4.7 **Change the release rule**: set `release.rule: unlimited` for push
release or `conwip` with `release.conwip_limit`.

4.8 **Verification mode**: set `simulation.deterministic: true` and
`simulation.breakdowns: false` to remove all randomness. Use it to compare the
model with a hand calculation.

4.9 After any change, run `make test` and then the baseline.

## 5. Defining and running a new scenario

5.1 Add a block to `config/scenarios.yaml`:

```yaml
  S7:
    name: "Batch size 40"
    description: "Larger batches halve the number of model switches."
    extends: [S2]                 # optional: build on an existing scenario
    overrides:
      orders: {batch_size: 40}
      stations:
        4: {ct_mean_s: {scale: 0.95}}     # 5 % faster brazing
        "1-3": {mttr_min: {add: -2}}      # 2 min faster repairs at S1-S3
      buffers: {all: 6}
```

5.2 Supported operators are a literal value, `{scale: x}` and `{add: x}`.
Station selectors are an id, an `"a-b"` range or `"all"`.

5.3 Run `make scenarios` (or `python -m evapsim scenarios`). Every scenario in
the file is simulated with the same seeds as S0, so results are directly
comparable (common random numbers).

5.4 Read `results/scenario_paired_differences.csv`. A scenario has a
statistically significant effect on a metric when `significant` is `True`,
which means the 95 % CI of the paired difference does not include 0.

## 6. Running the sensitivity analysis

6.1 Run `make sensitivity` (100 replications per run, about 5-8 minutes), or
`python -m evapsim sensitivity --reps 200` for tighter intervals.

6.2 The design changes each station's cycle time, MTBF and MTTR by ±10 %, and
all buffers by ±1 unit, one factor at a time.

6.3 Outputs: `results/sensitivity_oat.csv` (ranked by swing) and
`figures/sensitivity_tornado.png`. To add factors, extend `factors()` in
`src/evapsim/sensitivity.py`.

## 7. Using the dashboard

7.1 Start it with `make dashboard` (or `streamlit run app/dashboard.py`). It
opens at http://localhost:8501.

7.2 Sidebar:
1. **Scenario**: the starting configuration (S0-S6).
2. **Line parameters**: demand, buffer size (all buffers), release rule and
   CONWIP limit, batch size.
3. **Run settings**: replications (5-200), measured days, worker processes,
   and whether to compare with S0.

7.3 Edit the **station parameter table** in the main panel if needed. Leave
MTBF/MTTR empty for no breakdowns.

7.4 Press **Run simulation**. With 30 replications this takes about 5-15 s.
KPI tiles show the mean, with the paired difference against S0 underneath. Hover
over a tile to see its 95 % CI.

7.5 Tabs: lead-time distribution, station state breakdown (with a table),
bottleneck frequency, and the scenario comparison (this run vs S0, plus the
committed full-run results).

7.6 Results are cached for each exact parameter set, so pressing Run again
with the same inputs returns at once.

## 8. Reading the outputs

| Output | How to read it | What "good" looks like |
|---|---|---|
| **Throughput / attainment** | Mean good units per day, and that number divided by demand | Attainment ≥ 100 % with a CI that does not reach below 100 % |
| **Takt compliance** | Share of days that met demand | ≥ 95 % for a robust line. Below 50 % means the line is not capable |
| **Lead time mean / P95** | Release-to-exit time in productive minutes | P95 close to the mean (stable flow). A long P95 tail points to breakdowns or changeovers |
| **WIP vs Little's-law WIP** | The two estimates must agree | Within about 1 %. A larger gap suggests a measurement error |
| **Station state bar** | Shares of busy, changeover, down, blocked and starved | The bottleneck has the highest active share and is rarely starved or blocked. Upstream stations show *blocked*, downstream ones show *starved* |
| **Bottleneck frequency** | Share of replications in which each station is the bottleneck | One station close to 100 % = a stable bottleneck. A split = a shifting bottleneck, so improve both |
| **Paired differences** | Scenario minus S0 for the same replications, with a 95 % CI | The CI excludes 0 (significant) and the gain is big enough to matter in practice |
| **Tornado** | Throughput change for each ±10 % factor change | Long bars show where to focus improvement. Bars near zero show where effort is wasted |
| **Convergence** | Running mean and relative CI half-width | Half-width below the 1 % target line |
| **Validation** | % error, prediction-interval p-value | \|error\| ≤ 5 % and p ≥ 0.05 |
| **VSM** | Process data, inventory, timeline | Future state: less waiting, a higher VA ratio and the improvements marked as kaizen bursts |

## 9. Re-validating the model with new data

9.1 **Replace the time-study data**: keep the columns of
`data/time_study_samples.csv` (`station_id`, `observed_time_s`, ...) and record
at least 30 observations per station for the reference model. Run
`make input`, then copy the selected fitted mean and CV into
`ct_mean_s`/`ct_cv`.

9.2 **Replace the observed line data**: export MES or shift-log data in the
long format of `data/observed_line_data.csv`:

| Column | Meaning |
|---|---|
| `day`, `date` | Production day number and date |
| `record_type` | `daily_output`, `station_utilisation` or `batch_lead_time` |
| `entity` | `line`, a station (`S1`..`S7`) or a batch id |
| `value`, `unit` | The measurement and its unit (units, fraction, min) |

Lead times must be in *productive* minutes, so leave out breaks and time
between shifts.

9.3 Set `simulation.days` to the number of observed days, then run
`make baseline`.

9.4 Read `results/validation_summary.csv`. If |error| > 5 % or the
prediction-interval p-value is below 0.05:
1. Check the inputs first: MTBF/MTTR from the maintenance log, changeover
   times, scrap rates and the product mix of the period.
2. Use `validation_station_utilisation.csv` to find stations whose utilisation
   is off by more than 5 %. A station that is busier in reality than in the
   model has a cycle time that is too short in the model.
3. Change one parameter at a time, re-run and record each iteration in
   `docs/BUILD_PHASES.md` (Phase 6) with the reason for it.
4. Keep a hold-out period (for example the last 5 days) that is not used for
   calibration, and confirm the calibrated model against it.

9.5 Never tune a parameter that has a direct measurement just to make the
validation pass. Re-measure it instead.

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConfigError: Invalid configuration` | A range or consistency rule failed | Read the listed messages, for example mix ≠ 1 or the wrong number of buffer entries |
| `ModuleNotFoundError: evapsim` | Package not installed or path not set | `make setup`, or `export PYTHONPATH=src` |
| Results differ from the committed ones | The seed, config or replication count changed | Check `results/run_metadata.json` and `git diff config/`. With the same inputs, results are bit-for-bit identical, whatever the number of workers |
| Running mean still drifts in the first days | Warm-up too short (for example after a large CONWIP or buffer increase) | Increase `simulation.warmup_days` and plot the mean output per day across replications from `*_daily_output.csv` |
| CI too wide | Too few replications | Use `convergence_required_replications.csv` to choose *n*, then re-run with `--reps n` |
| Scenario difference not significant | The effect is small compared with the noise | More replications. Check that `crn_corr` is high, which confirms CRN is working |
| Run is very slow | Single worker, or a very long horizon | Set `--workers`. Remember that run time grows with days × replications × throughput |
| Dashboard hangs at "Running" | Process pool cannot start in the environment | Set *Worker processes* to 1 |
| `make` not found (Windows) | No GNU make | Run the `python -m evapsim <step>` commands from the Makefile directly |

## 11. Version control and change-log practice

11.1 Every change to `config/` gets a commit with a conventional-commit
message, for example `feat(config): raise S4 MTBF after PM programme`, and a
higher `meta.config_version` (semantic versioning: major = structural change,
minor = parameter change, patch = comment or typo).

11.2 Re-run the affected steps and commit the regenerated `results/` in the
same commit, so results always match the configuration next to them.

11.3 Run `make report` after re-running so the README and docs tables are
regenerated from the CSV files. Never edit numbers in generated blocks by hand.

11.4 Record calibration and modelling decisions in `docs/ASSUMPTIONS.md` with
a new ID, and add any problem you hit to `docs/BUILD_PHASES.md`.

11.5 CI (ruff, pytest and a 10-replication smoke run) must be green before
merging.

### Results sign-off checklist

- [ ] `make lint test` is green locally and in CI.
- [ ] The run used the full mode (500 replications), as shown in `results/run_metadata.json`.
- [ ] The convergence half-width for throughput is ≤ 1 % of the mean.
- [ ] Validation: |error| ≤ 5 % for output and lead time, and prediction-interval p ≥ 0.05.
- [ ] Little's law: WIP and Little's-law WIP agree within 1 % (`baseline_kpis.csv`).
- [ ] The bottleneck station agrees with the static capacity check and the state bars.
- [ ] Every scenario claim is supported by a paired 95 % CI that excludes 0.
- [ ] `make report` was run, and the README/docs tables match `results/*.csv`.
- [ ] Assumptions, deviations and config version are documented.
- [ ] Reviewer name and date are recorded in the pull request.
