# Assumptions and design decisions

> **All data in this project is fictional.** The line, its parameters, the
> time-study samples and the "observed" line data were invented for a
> portfolio project and do not describe any real company, plant or product.

This file records every assumption made where the project brief was silent or
ambiguous, so a reviewer can see exactly what was decided and why. IDs are
referenced from code comments and the other documents.

## 1. Problem definition and scope

| ID | Assumption | Rationale |
|---|---|---|
| A1 | The system boundary is the line from release into Station 1 to the exit of Station 7. Raw-material and finished-goods stores are outside the simulation and appear only on the VSM (`vsm.raw_material_stock_days`, `vsm.finished_goods_stock_days`). | The brief describes the seven stations and their buffers. Store levels are policy decisions that the line model cannot predict. |
| A2 | The line is **saturated**: raw material is always available, so throughput is set by line capacity, not by order arrivals. | The brief gives an unlimited raw-material buffer. With demand above capacity (see A20), a demand-driven arrival process would make the queue grow without limit and lead time would depend on the horizon. |
| A3 | Simulated time is **productive time only**. One day = 480 min of net productive time. The line freezes at the end of a shift and resumes with the same WIP the next day, so no events happen between shifts. | The brief states 480 net productive minutes after breaks. Nothing changes state between shifts on a one-shift line. |
| A4 | "20 production days with 1 day warm-up" means **21 simulated days**. Day 1 is discarded and days 2-21 are measured. | This keeps 20 measured days in each replication, which matches the 20 days of observed data. |
| A5 | Lead time is **line lead time**: the time from release into Station 1 to exit from Station 7, in productive minutes. It is also reported in shift-days (minutes / 480). | Lead time must be measured inside the model boundary (A1). The VSM door-to-door lead time adds the store days from A1. |

## 2. Products, orders and release

| ID | Assumption | Rationale |
|---|---|---|
| A6 | Orders are batches of 20 units of one model. The batch sequence is random, and each batch's model is drawn independently using the mix probabilities (30/50/20). | No sequencing rule was given. Independent draws are the neutral choice. The expected share of batches that switch model is 1 - (0.3² + 0.5² + 0.2²) = 62 %. |
| A7 | Each unit's cycle time at every station is the station's lognormal variate multiplied by the model's multiplier (0.85 / 1.00 / 1.25). Rework, changeover and repair times do not depend on the model. | This follows the brief. The demand-weighted average multiplier is 1.005. |
| A8 | **CONWIP**: Station 1 may start a new unit only while fewer than `conwip_limit` units are in the line. A unit holds its card from release until it exits or is scrapped. **Unlimited**: Station 1 starts a new unit whenever it is free. | This is the standard CONWIP card loop. Releasing a unit when Station 1 pulls it puts the authorisation point at the line entrance, which is where the WIP limit applies. |
| A9 | A scrapped unit is not replaced, so its batch finishes short. | This is the simplest rule. Replacing scrapped units would need an order-management policy that the brief does not give. |
| A10 | The line is set up for the first batch's model at time 0, so the first unit triggers no changeover. | This avoids an artificial changeover at the start. The warm-up period removes the effect either way. |

## 3. Stations, buffers and failures

| ID | Assumption | Rationale |
|---|---|---|
| A11 | The cycle-time mean and CV in the YAML refer to the **Medium** model (multiplier 1.00). Time-study samples are of the Medium model. | Engineering standards are usually set for a reference model. |
| A12 | Breakdowns are **operation-dependent**. Each machine keeps an exponential time-to-failure clock (mean MTBF) that runs only while it is processing, including rework. Repair time is exponential (mean MTTR). A part being processed when the machine fails resumes after repair without losing work. | The brief says "exponential MTBF/MTTR, only while processing". Resuming work is the usual assumption for assembly operations. |
| A13 | A changeover happens when the next *new* unit's model differs from the last model the machine processed. Its duration is lognormal with the configured mean and CV 0.10 (`simulation.changeover_cv`). Changeover time is not operating time, so it does not advance the failure clock. Each parallel machine changes over independently. | A small amount of variability is realistic. With CV set to 0, changeovers are fixed, as in verification mode. |
| A14 | Inter-station buffers are finite (5 units in the baseline). A finished unit stays on its machine until the downstream buffer has space (**blocking after service**). Station 7 feeds an unlimited finished-goods area. | This follows the brief. |
| A15 | Parallel servers (Station 6, and Station 4 in S3) share one input buffer, which they take from in FIFO order. | This is a standard multi-server queue. |
| A16 | Scrap is decided when processing at a station finishes, by an independent Bernoulli trial at the station's scrap rate. A scrapped unit leaves the line right away and frees its CONWIP card. | This follows the brief. |
| A17 | **Rework loop**: a unit that fails the Station 5 test (2.5 %) is reworked at Station 4 with probability 0.40 and is otherwise scrapped. Reworked units wait in a dedicated rework queue at Station 4 that has priority over new work and does not use buffer slots. Rework takes lognormal(90 s, CV 0.20), triggers no changeover and does not change the fixture set-up. After rework the unit goes back through the 4→5 buffer for a complete re-test. A unit that fails a second time is scrapped (`max_reworks_per_unit: 1`). | If returned units had to use the finite 4→5 buffer in reverse, the loop could deadlock: Station 5 would be blocked by a full Station 4 input while Station 4 was blocked by a full 4→5 buffer. A separate priority rework queue is a common real-life layout (a rework rack) and cannot deadlock. |

## 4. Statistical design

| ID | Assumption | Rationale |
|---|---|---|
| A18 | Replication *r* of every scenario uses the same `SeedSequence(base_seed, spawn_key=(r, stream))` streams: one for orders and unit attributes, plus one per machine for failures and changeovers. Each unit carries its own pre-drawn normals and uniforms, so the same unit gets the same relative cycle times and quality outcomes in every scenario. | This gives **common random numbers** with good synchronisation, which reduces the variance of paired differences between scenarios. |
| A19 | Confidence intervals are Student-t intervals on replication means. Scenario comparisons use the **paired-t** method on differences per replication against S0. | Replication means are independent and close to normal, by the CLT over 20 days. Pairing uses the CRN correlation. |
| A20 | The baseline parameters are used **exactly as given in the brief** and were not tuned to look good. A static capacity check (see `docs/MODEL_DESCRIPTION.md`) shows the brazing station's effective time per unit, including breakdowns and changeovers, is far above takt. A large shortfall against takt is therefore expected, and it is what the brief asks the analysis to show. | Changing the parameters to shrink the gap would misrepresent the brief. Scenario S6 (an addition) tests what it takes to reach takt. |

## 5. Metrics

| ID | Assumption | Rationale |
|---|---|---|
| A21 | **Bottleneck detection** uses the *active-period* share = busy + down + changeover, which equals 1 - starved - blocked. The station with the highest active share in a replication is that replication's bottleneck. The brief's literal "busy + blocked" share is also computed and reported, but it is **not** used, because it ranks stations that are blocked by the bottleneck (Stations 1-3) above the bottleneck itself. See BUILD_PHASES, Phase 4. | A blocked station is waiting for its downstream neighbour, which is a symptom of a constraint downstream, not a constraint itself. |
| A22 | Utilisation = share of scheduled time a machine spends processing (busy), averaged over the station's parallel servers. | This is the conventional definition. Down and changeover time are reported separately. |
| A23 | First-pass yield (line) = units that leave Station 7 without ever failing a test or being scrapped / units that finished (left the line good or scrapped) during the measurement window. Station FPY = 1 - scrap (or fail) share at that station. | These are the standard FPY and RTY definitions. |
| A24 | VSM value-added time = the processing time at each station (cycle time), as on a conventional VSM. Test, inspection and packing are counted as processing time. The line VA ratio is mean VA time per good unit / mean line lead time. The door-to-door VA ratio also includes the raw-material and finished-goods store days from A1. | This is conventional VSM practice. The lean distinction between value-adding and necessary non-value-adding work is listed under limitations. |
| A25 | Days of stock = average units in a buffer / daily customer demand (380). | This is the standard VSM conversion. |
| A26 | Takt compliance = share of measured days with output >= 380 good units. | This follows the brief. |

## 6. Data generation

| ID | Assumption | Rationale |
|---|---|---|
| A27 | Time-study samples: 40 stopwatch readings per station of the Medium model, drawn from lognormal(mean, CV) with seed 1101 and rounded to 0.1 s. Station 6 readings alternate between workstations 6A and 6B. | This follows the brief. Rounding mimics stopwatch resolution. |
| A28 | "Observed" line data: one 21-day run (day 1 discarded) of a **perturbed** model, with seed 7707. Each station's mean cycle time is multiplied by N(1, 0.02), and its MTBF and MTTR by N(1, 0.08). It is exported as an MES-style long table (daily output, daily station utilisation, lead time of each completed batch), with dates on weekdays from 2 March 2026. | The perturbation stands in for real-world model error, so the validation has something to detect without being trivially exact. |

## 7. Repository and tooling

| ID | Assumption | Rationale |
|---|---|---|
| A29 | The project lives in the `evaporator-line-des/` folder of an existing portfolio repository, which already had git history, so no new `git init` was needed. The project keeps its own `.github/workflows/ci.yml`, so it can be split into a standalone repository. A copy at the repository root (`.github/workflows/evaporator-line-des-ci.yml`) runs the same checks inside the folder so CI works in its current location. | GitHub Actions only reads workflows from the repository root. |
| A30 | `observed_line_data.csv` was designed in Phase 1 (the data dictionary and perturbation spec above), but it is generated by the simulation engine, so it was produced and committed with Phase 3, once the engine existed. | The brief asks for data from "a slightly perturbed version of the model", so the model has to exist first. |
| A31 | A seventh scenario, **S6 = S5 + second brazing fixture**, was added beyond the S0-S5 brief. | S5 does not reach takt (see results). S6 shows what a recommendation that closes the gap would need. |
| A32 | Sensitivity analysis uses 100 replications per run, not 500, and CRN against a baseline with the same 100 replications. Buffer size is varied by ±1 unit on all buffers (5 → 4 / 6), because ±10 % of 5 is not an integer. | Paired CRN differences are precise enough at 100 replications, and 36 runs × 500 replications would take hours. |
