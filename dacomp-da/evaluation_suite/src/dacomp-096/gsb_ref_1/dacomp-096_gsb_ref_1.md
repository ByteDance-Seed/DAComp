# Campaign Health Framework and Diagnostic Report

Note on data availability
- The database does not include klaviyo__campaigns or marts.klaviyo__persons. I used klaviyo__flows as a proxy for campaigns and klaviyo__person_campaign_flow for person-level touch metrics where available.
- EMAIL_TEMPLATE_ID is not present; I used variation_id as a proxy for template identity.

Time window for baselines
- Last 6 months window: 2023-06-14 to 2023-12-13 (based on max updated_at = 2023-12-13 17:30:00).

Core metrics and grouping
- Open Rate (OR) = count_opened_email ÷ count_received_email
- Click-to-Open Rate (CTOR) = count_clicked_email ÷ count_opened_email
- Campaign Type (heuristic from flow_name): Promotional / New Product / Storytelling
- Theme (from flow_name): Abandonment - Browse, Abandonment - Cart, Lifecycle - Post-Purchase, Discovery, Seasonal, Loyalty, Welcome, Winback
- Audience size bins by count_received_email: <10k, 10k–100k, >100k

Anomaly detection rules
- Performance anomalies: For each campaign, OR and CTOR are compared to mean ± 2σ from the last 6 months for its Campaign Type × Audience Bin. Values below mean − 2σ or above mean + 2σ are flagged.
- High-frequency update anomalies: Intervals <24 hours between a campaign’s updated_at and the previous one.

Visualization
- See campaign_health.png (left: OR vs CTOR with anomalies; right: CTOR by theme with error bars).

![campaign_health.png](campaign_health.png)

What the data shows
- Baselines by Campaign Type × Audience Bin (last 6 months):
  - All observed campaigns fall into the <10k audience bin in the last 6 months. For this bin:
    - New Product: OR ≈ 0.488 (σ ≈ 0.030); CTOR ≈ 0.240 (σ ≈ 0.036)
    - Promotional: OR ≈ 0.418 (σ ≈ 0.043); CTOR ≈ 0.242 (σ ≈ 0.048)
    - Storytelling: OR ≈ 0.403 (σ ≈ 0.050); CTOR ≈ 0.239 (σ ≈ 0.045)
- Theme performance (CTOR, last 6 months):
  - Highest: Loyalty (~0.267), Abandonment - Browse (~0.250), Winback (~0.250)
  - Lowest: Lifecycle - Post-Purchase (~0.220), Seasonal (~0.223), Welcome (~0.230)
- Send time effects (last 6 months averages):
  - CTOR: Afternoon ≈ 0.244; Evening/Night ≈ 0.242; Morning ≈ 0.233
  - Open Rate: Weekend ≈ 0.428 vs Weekday ≈ 0.419; CTOR: Weekend ≈ 0.246 vs Weekday ≈ 0.238
- Cadence and anomalies:
  - High-frequency update anomalies: none found; typical intervals ~96–98 hours; minimum ~61 hours.
  - Performance anomalies (OR/CTOR beyond mean ± 2σ): none detected in the last 6 months.
- Template reuse:
  - No single variation_id (template proxy) exceeds 50% share; top templates are each ~4.3% of sends in the last 6 months.
- Person-level alignment:
  - The person-level table has very limited coverage (4 rows) in the time window and a single source_relation, so cross-validation at the touch level is inconclusive. Variation-level comparisons show that some high-volume templates (e.g., VAR-019 with CTOR ~0.170) underperform peers despite similar OR ranges.

Diagnosis and likely causes
- No formal anomalies were triggered, but relative underperformance clusters exist:
  - Themes: Lifecycle - Post-Purchase, Seasonal, and Welcome have consistently lower CTOR.
  - Send-time: Morning sends have lower CTOR than Afternoon/Evening; weekend sends slightly outperform weekdays on both OR and CTOR.
  - Templates: Although overall reuse is diversified, specific high-send templates like VAR-019 show materially lower CTOR, suggesting creative fatigue or misfit for the target audience.
- Copy theme signals via source_relation are not differentiating here (single value), so theme diagnosis relies on flow_name mapping. This indicates a taxonomy gap in tracking copy themes explicitly.

Prescriptive guidance (what actions to take)
1) Template governance
   - Keep single-template share below 40–50% as a guardrail (currently met).
   - Identify low-performing high-volume templates (e.g., VAR-019) and prioritize redesign. Replace hero image, simplify layout, shorten copy, reduce friction in primary CTA.
   - Institute a rotation policy: limit consecutive deployments of the same template to reduce fatigue.
   - Set a quarterly template audit to retire the bottom quartile by CTOR or refresh the creative.

2) Theme optimization
   - Prioritize testing for Post-Purchase, Seasonal, and Welcome themes, which show CTOR ≈ 0.22–0.23 (5–10% below top themes).
   - Hypothesized levers:
     - Stronger value propositions in early paragraphs (Welcome, Post-Purchase).
     - Personalization tokens (order category, loyalty tier) and conversational tone for Post-Purchase.
     - Seasonal urgency framing with time-bound offers, and clearer product tie-ins.

3) Sending cadence
   - Maintain spacing ≥48–72 hours for flows acting like campaigns; current intervals are healthy (median ~98 hours).
   - Explicitly prevent <24h deployments to avoid list fatigue and potential deliverability degradation (no current violations, keep the rule enforced).

4) Send-time optimization
   - Shift a portion of Morning deliveries to Afternoon or Early Evening; these slots show higher CTOR by ~0.009–0.011 absolute.
   - Allocate more weekend sends where feasible, given modest lifts in OR (+0.009) and CTOR (+0.008).

Anomaly playbook (framework to monitor continuously)
- For every deployment:
  - Compute OR and CTOR, map to Campaign Type × Audience Bin baseline from the trailing 6 months, and flag if outside mean ± 2σ.
  - Compute delta to previous updated_at; flag if <24 hours.
  - Record template_reuse_pct by template ID and flag if >50%.
  - Capture send time (weekday/weekend; morning/afternoon/evening) and theme tags; tie anomalies back to these facets to isolate likely drivers.
- For flagged cases:
  - If OR is anomalously low: prioritize subject line and preheader testing; review send-time and audience saturation.
  - If CTOR is anomalously low: prioritize creative/template/CTA testing; review relevance of theme and placement of key CTAs above the fold.
  - If cadence <24h: reschedule to protect engagement and deliverability KPIs.

A/B test plan (actionable and measurable)
- Test 1: Send-time shift (Morning vs Afternoon)
  - Audience: upcoming Promotional deployments in the <10k bin.
  - Split: 50/50 holdout.
  - Hypothesis: Afternoon increases OR by 5–10% relative and CTOR by 2–5% relative vs Morning, based on observed averages (Afternoon CTOR ~0.244 vs Morning ~0.233; Weekend uplift vs Weekday).
  - Success metrics: Lift in OR and CTOR; secondarily, downstream conversion events if available.

- Test 2: Template refresh for underperformer (e.g., VAR-019)
  - Changes: new hero asset, streamlined copy, clearer single primary CTA, reduce above-the-fold friction.
  - Split: A (current) vs B (refresh), 50/50 on the same audience/theme.
  - Expected gains: CTOR +5–10% relative; OR neutral to +3% if subject line is also tuned.

- Test 3: Theme framing for Post-Purchase
  - Variant A: transactional-plus-value (how-to use, warranty, tips) with soft cross-sell.
  - Variant B: benefit-led cross-sell with personalized picks and social proof.
  - Expected gains: CTOR +3–6% relative; longer-term net revenue per recipient uplift if tracked.

Governance metrics to track weekly
- OR and CTOR by Campaign Type × Audience Bin (6-month rolling means and σ).
- Anomaly counts and reasons (performance vs cadence).
- Template share distribution with guardrail alerts at >40–50%.
- Theme performance ranks and trend movements.
- Send-time performance by daypart and weekday/weekend.
- Person-level corroboration for top templates if/when coverage improves.

Limitations and data gaps
- The last 6 months include only <10k audience sends, so baselines for larger bins are not populated.
- source_relation lacks variation; adding explicit copy theme tags at the campaign level would improve diagnosis.
- Person-level table coverage in-window is minimal; as coverage grows, compare flow-level and touch-level OR/CTOR to validate creative effectiveness by segment.

Appendix: Key numeric highlights
- No campaigns flagged as OR/CTOR anomalies (mean ± 2σ) in the last 6 months.
- No high-frequency (<24h) cadence anomalies; median interval ~98 hours.
- Lowest CTOR themes: Post-Purchase (~0.220), Seasonal (~0.223), Welcome (~0.230).
- Send-time: Afternoon and Evening/Night outperform Morning on CTOR; weekend outperforms weekday on both OR and CTOR.
