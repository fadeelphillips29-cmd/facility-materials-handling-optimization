# Assumptions, decisions and data dictionary

> **Illustrative and anonymised data.** The organisation is called "the
> Company". Every time and probability below is an illustrative or anonymised
> input, used to demonstrate the method. None of them is measured company
> data. `time_scale_factor` in `config/line_parameters.yaml` rescales every
> process time before publication.

Each input has a **source tag**:

| Tag | Meaning |
|---|---|
| **time study** | Taken from the (anonymised) time study or whiteboard |
| **estimate** | An estimate that still needs a proper time study (steeking) |
| **assumed** | An engineering assumption made for this model, to be replaced by data |

## 1. Input register (data dictionary)

This table is generated from `config/line_parameters.yaml` by `make report`.

<!-- BEGIN:input_register -->
| Input | Value | Unit | Source |
|---|---|---|---|
| fin_press.nominal_rate_fpm | 75 | fins/min | time study |
| fin_press.good_fins_per_eva | 4000 | fins/EVA | time study |
| fin_press.setup_min | 30 | min/job | time study |
| fin_press.setup_cv | 0.25 | - | assumed |
| fin_press.performance | 0.95 | - | time study |
| fin_press.quality | 0.98 | - | time study |
| fin_press.mtbf_min | 270 | min run time | time study |
| fin_press.mttr_min | 30 | min | time study |
| fin_press.mttr_cv | 0.5 | - | assumed |
| fin_press.reel_fins | 8000 | fins/reel | time study |
| fin_press.reload_min | 5 | min/reel | time study |
| operations.boxing | 100 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.trim_tubes | 40 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.weld_hairpins | 54 x 4 min, CV 0.12, crew 1 | per EVA | time study |
| operations.steeking | 420 min, CV 0.2, crew 2 | per EVA | estimate |
| operations.weld_return_bends | 36 x 4 min, CV 0.12, crew 1 | per EVA | time study |
| operations.expansion | 24 x 3 min + 15 min, CV 0.1, crew 1 | per EVA | time study |
| operations.prepare_headers | 120 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.header_welding | 48 x 8 min, CV 0.15, crew 1 | per EVA | time study |
| operations.wash | 45 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.pressure_test | 90 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.press_brake | 40 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.flat_welding | 90 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.plenum_assembly | 60 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.drip_tray_weld | 100 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.drip_tray_assembly | 45 min, CV 0.15, crew 1 | per EVA | assumed |
| operations.complete_assembly | 150 min, CV 0.15, crew 2 | per EVA | assumed |
| lead_times.engineering_release | 1.0 d, CV 0.3 | working days | assumed |
| lead_times.procurement_sheet_metal | 4.0 d, CV 0.25 | working days | assumed |
| lead_times.procurement_tubing | 8.75 d, CV 0.3 (brief 8.0 d) | working days | assumed, calibrated (A35) |
| lead_times.drip_tray_external | 5.0 d, CV 0.3 | working days | assumed |
| lead_times.coating | 3.0 d, CV 0.3 | working days | assumed |
| rework | p = 0.04, 60 min | - | assumed |
| demand.eva_per_week | 3.0 | EVA/week | time study (whiteboard, to confirm) |
| demand.interarrival_cv | 0.25 | - | assumed |
| demand.due_date_weeks | 6.0 | weeks | assumed |
| crew_efficiency | {1: 1.0, 2: 1.0, 3: 0.85, 4: 0.75} | eta(crew) | assumed |
| input_uncertainty.steeking_triangular_min | [360, 420, 600] | min/EVA | estimate |
<!-- END:input_register -->

## 2. Process structure

| ID | Assumption / decision | Rationale |
|---|---|---|
| A1 | The unit of flow is the **EVA** (one evaporator). Work orders of B = 3 EVA are released together, so the process lot is 3. The transfer batch between stations is 3 in the baseline and can be set to 1. | Brief. |
| A2 | **Order of cleaning and testing**: `wash_before_test: true` (Cleaning, step 11, comes before Pressure test, step 12), following the written steps. The original flowchart shows the reverse order, which `wash_before_test: false` reproduces. | The written steps are more specific than the flowchart. Both orders are supported and documented. |
| A3 | **Engineering drawing release** is a calendar delay (lognormal, mean 1 working day, CV 0.30 assumed). It has no capacity limit. | No engineering capacity data were given. |
| A4 | Sheet metal and tubing are **ordered at drawing release**. Fin-press setup and punching start at drawing release too, in parallel with procurement (step 3). | Brief, steps 2-3. |
| A5 | **Tube-dependent steps** wait for tubing: boxing (modules are tubes), trim tubes, weld hairpins and **prepare headers** (header pipe is assumed to be part of the tubing order). Stainless strip for the fin press and the end panels are stock items. | Brief: "the order cannot start the tube-dependent steps until tubing arrives". Header material is not specified, so this is an assumption. |
| A6 | **Boxing** is done by the fin-press operator. For each EVA it needs that EVA's fin pack *and* the tubing. The operator holds the fin press for the whole job (setup plus all B EVA), and then competes FIFO for boxing work with fin-press jobs of other orders. | Brief steps 4-5: "the same operator". |
| A7 | **Joins.** Steeking of an EVA needs its fin pack, its boxed module and its circuits. Header welding needs the expanded coil and the prepared headers. Complete assembly needs the coil (after coating), the plenum and the drip tray of the same EVA. A join waits until every input is present (`test_join_never_starts_early`). | Brief. |
| A8 | **Steeking** uses one steeking fixture worked by a crew. The elapsed time is labour content / (crew × eta(crew)), with labour = 420 min × 2 = 840 operator-min per EVA, eta(2) = 1 and eta(3) = 0.85. A third operator therefore gives 329.4 min/EVA. | Brief equation B. One coil is laced at a time. |
| A9 | **Pressure-test failure**: each test fails independently with p = 0.04 (assumed). A failed coil is repaired for 60 min by the **header welder** (the rework resource, assumed), and then retested. It is not re-washed. | Brief: "60 min weld repair at the header/return-bend operator". Header joints are assumed to be the usual leak point. |
| A10 | **Outsourced coating** (powder coat / galvanising, flag on by default) is a calendar delay applied to each transfer batch of coils after the final test. Outsourcing capacity is unlimited. | External suppliers' capacity is outside the model. |
| A11 | **Drip tray**: the sheet plates go out for bending and punching as one lot per work order. After they return, they are welded (drip-tray welder) and assembled (the sheet-metal assembler, who also assembles plenums). | Brief step 14. |
| A12 | **Complete assembly** uses a 2-person crew for 150 min elapsed per EVA (labour 300 operator-min). | Brief. |
| A13 | Inter-station queues are **unlimited**, so no resource is ever *blocked*. The blocked state is still tracked (and is always 0) so the state model matches the brief. Its share is reported as 0 with this explanation. | A low-volume, engineer-to-order shop does not have kanban-limited buffers. Waiting WIP shows up as queue time instead. |
| A14 | Queues are FIFO by request time. Rework jobs have priority at the header welder. | Neutral dispatching, plus fast repair of failed coils. |

## 3. Time base, calendar and demand

| ID | Assumption / decision | Rationale |
|---|---|---|
| A15 | Clock = **working minutes**: 480 per day, 5 days per week (2,400 per week). Nights and weekends are not simulated. Procurement and outsourcing lead times are in working days. | Brief. |
| A16 | **Run length**: 8 warm-up weeks are discarded, then **52 weeks are measured** (one full year), so 60 simulated weeks in total. | A 52-week measured year is the planning horizon. A single order takes about 4.4 weeks in the empty system, so an 8-week warm-up fills the pipeline. |
| A17 | **Demand**: work orders arrive with mean interarrival B / demand weeks. The baseline is 1 order of 3 EVA per week (whiteboard, to be confirmed). Arrivals are lognormal with CV 0.25 (assumed order-intake variability). The demand sweep uses 3, 4, 5, 5.5 and 6 EVA/week. | The brief gives the rate. A small amount of arrival variability is realistic, and the Kingman check needs it. |
| A18 | **Due date** = arrival + 6 weeks (assumed promised lead time), used for on-time delivery. | No promise date was given. The hand-calculated lead time of a single order is about 4.4 weeks, so 6 weeks includes some slack. |
| A19 | **Order lead time** runs from the order's arrival (before drawing release and any CONWIP wait) to the completion of its last EVA. EVA lead time runs from the order's arrival to that EVA's completion. | This is the customer-facing lead time. |
| A20 | `time_scale_factor` multiplies every **process** time: operation times, rework, fin-press setup, run time (through the rate), reel reload and MTTR. MTBF is scaled too, so availability and OEE do not change. Calendar delays (engineering, procurement, outsourcing) are **not** scaled. | Lets the author anonymise touch times without changing the structure of the results. |

## 4. Fin press

| ID | Assumption / decision | Rationale |
|---|---|---|
| A21 | Calibrated parameters: F = 4,000 good fins per EVA, S = 30 min, P = 0.95, Q = 0.98, MTBF = 270 min of run time, MTTR = 30 min (A_u = 0.90), reel R = 8,000 fins, reload t_r = 5 min. Equations A1-A5 give **T_job = 228.6 min per 3 EVA** (76.2 min/EVA) and **OEE = 69.99 %**. The whiteboard figure of 229 min is this value rounded. All tables use the exact value, 228.6 min. | Brief eq. A8: F = 0.70 × 75 × 229 / 3 = 4,007.5 ≈ 4,000. |
| A22 | Stochastic fin press (eq. A9). Setup is lognormal (CV 0.25). Scrap is Bernoulli(1 - Q) per fin, so the scrap count per EVA follows a negative binomial. Run time = gross fins / (r_n · P). Unplanned stops arrive at rate 1/MTBF of **run time**, with lognormal repairs (mean MTTR, CV 0.50 assumed). The reel is changed (t_r) every R gross fins, and the reel carries over between EVAs and jobs. Setup and reel changes are recorded as *changeover*, repairs as *down*. | Brief A9. The simulated mean must be within 1 % of T_job/B (test). |
| A23 | **Scenario S4 (OEE 70 % → 85 %).** The analytical model shows that SMED alone (setup -40 %, to 18 min) only raises OEE to **73.9 %**. With S = 18 min, Q = 0.98 and a 5-min reel change, OEE is capped at 84.7 % even with perfect availability and speed. Reaching 85 % therefore needs a package: setup 18 min, MTBF 540 min, MTTR 10 min, P = 0.985, Q = 0.99 and a 2-min quick reel change, which gives OEE = 85.0 %. This is recorded as a deviation from the brief's "SMED + reduced stops", which cannot reach 85 % on its own. | Found while building the analytical model (BUILD_PHASES, Phase 2). |

## 5. Variability and statistics

| ID | Assumption / decision | Rationale |
|---|---|---|
| A24 | Process times are **lognormal** with the standard time as the mean. CVs (assumed): fin-press job 0.10 (time-study data only; the DES builds the fin press up mechanistically, A22), hairpins 0.12, steeking 0.20, return bends 0.12, expansion 0.10, header welding 0.15, everything else 0.15. The family of each operation is chosen by the Phase 3 rule (KS screen, then lognormal unless another family beats it by more than 2 AIC units). This selects the **lognormal for 16 of 17 operations** and the **Weibull for steeking** (lognormal ΔAIC = 2.2). The model uses the selected family with the stated mean and CV, and a Phase 7 robustness run swaps steeking back to lognormal. | Brief. Following the documented rule is more honest than overriding it, even though n = 40 barely discriminates. |
| A25 | **Deterministic (verification) mode**: every CV is 0, there are no fin-press stops or scrap (the analytical T_eva is used instead), no test failures, arrivals are exactly periodic and calendar delays are at their means. | It must reproduce the hand calculation exactly. |
| A26 | **Common random numbers.** Each work order draws its own standard normals and uniforms (for every operation of every EVA, its delays and its test outcomes), in arrival order, from stream `(rep, 0)`. The fin press uses its own stream `(rep, 1)`, and the outer-loop input sample uses `(rep, 9)`. Changing a mean, crew size, demand level or scenario therefore keeps the random events paired. | Variance reduction for the paired comparisons. |
| A27 | **Two-level Monte Carlo**: the outer loop samples the steeking mean from triangular(360, 420, 600) min/EVA (mean 460) once per replication. The variance decomposition uses a nested design (40 outer samples × 10 inner replications) and one-way random-effects ANOVA. The steeking cases at 6, 7, 16 and 20 h are run as separate deterministic-mean sensitivity cases. | Brief. Steeking is the least certain and most important input. |
| A28 | Confidence intervals are Student-t intervals on replication means. Scenario differences use the paired-t method against S0, at the same demand level. | These are standard simulation output-analysis methods. |
| A29 | **Bottleneck per replication** = the resource with the highest active share (busy + changeover + down). The resource with the longest mean queue time is reported as a second measure. | Brief: "highest utilisation or queue". |
| A30 | **Value-added time** = the sum of in-house processing times per EVA (all operations and the fin press). Delays, queues and outsourced lead times count as non-value-added. VA ratio = VA time / order lead time. | Conventional VSM practice. |

## 6. Validation data

| ID | Assumption / decision | Rationale |
|---|---|---|
| A31 | `data/observed_weekly_output.csv` contains 26 weeks of "measured" output and order lead times. It comes from one run of a **perturbed** model (process means × N(1, 0.04), procurement means × N(1, 0.06), seed 4242) after an 8-week warm-up. | The perturbation plays the role of real-world model error. |
| A32 | In a stable open system, throughput **equals demand**, so the weekly-output comparison is a consistency check. **Order lead time is the measure that discriminates between models**, with a target error of 5 % or less. | This is how open queueing networks behave. It is stated so the validation is not overclaimed. |

## 7. Repository

| ID | Assumption / decision | Rationale |
|---|---|---|
| A33 | This is **version 2** of `evaporator-line-des` and it replaces the earlier flow-line prototype (v1, still in the git history at commit `09a967f`). It lives in a sub-folder of an existing repository, so there was no new `git init`. A root-level CI workflow runs the checks inside the folder. | The brief's "git init" does not apply inside an existing repository. |
| A34 | Sensitivity and sweep runs use 100 replications per point (`simulation.sensitivity_replications`) instead of 300. All points are paired through CRN. | Paired differences are precise at n = 100. Runtime stays reasonable. |

## 8. Calibration and analytic cross-checks (added in Phase 6)

| ID | Assumption / decision | Rationale |
|---|---|---|
| A35 | **Calibration of the tubing lead time.** With the brief value of 8.0 working days, the model was 7.9 % below the observed mean order lead time (prediction-interval p = 0.02), outside the 5 % target. Tubing procurement is the most influential *assumed* input on the critical path. A grid search from 8.0 days in 0.25-day steps (`results/calibration_grid.csv`) used the **minimum-change rule**: adopt the smallest adjustment that passes both criteria. That gives **8.75 days**. The best-fit value, 9.75 days, was rejected because a single 26-week observation carries about ±2.7 % sampling noise. (The hidden "true" perturbed value is 8.94 days, so the minimum-change value is the closer of the two.) `brief_mean_days: 8.0` is kept in the YAML for traceability. | Brief: "if not, calibrate and document". Minimum change avoids overfitting the noise in one observation. |
| A36 | **Kingman in the network.** Lot arrivals at steeking are order releases plus independent random delays (procurement, engineering, upstream work). Successive gaps are negatively correlated, so the stream is not a renewal process. Kingman with the *measured* interarrival SCV overstates the queue and Kingman with the *release* SCV understates it. The simulation is required to fall between the two, and it does at every demand level. Header welding gets arrivals already spaced by the upstream bottleneck (steeking), so Kingman is not expected to hold there and the simulated queue is far below it. The strict Kingman test uses a single-station M/G/1 bench, where Kingman equals the exact Pollaczek-Khinchine result. | Shows where the analytic approximation applies and where it does not. |
