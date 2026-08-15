# POI selection and route quality

Rules for turning raw Amap candidates into a small set of routes worth showing.

## Selecting one POI per branch

Given up to 12 candidates for a plan, judge them in this order:

1. **Fit** — does the place actually deliver the plan's theme? A convenience store does not
   satisfy 咖啡漫步; a wedding photography studio does not satisfy 拍照打卡.
2. **Distance** — respect the search center. Under 附近 intent, prefer walkable options and
   reject anything that turns the evening into a commute.
3. **Quality signals** — rating, then whether photos exist, then whether the address and business
   area look complete.
4. **Time fit** — a bar at 10:00 or a park at 22:00 is a bad pick even if it rates well.
5. **Variety within the route** — avoid a second stop in the same category as the previous one
   unless the user asked for it (a food crawl is a valid exception).

Record for the chosen POI: name, address, coordinates, rating, per-person cost, distance from the
search center, and one sentence explaining the choice.

Return "no suitable POI" when every candidate fails step 1 or step 2. A weak route damages trust
more than a missing one.

### Reject outright

- Names containing 暂停开放, 暂未开放, 已关闭, or 停业.
- Missing coordinates.
- Administrative or non-visitable entries (管理处, 办公室, 停车场) unless explicitly requested.

## Estimating durations

Use these defaults when the plan does not specify one:

| Category | Minutes |
| --- | --- |
| restaurant | 90 |
| tourism, culture | 75 |
| everything else | 60 |

## Scoring a route

Rank routes by:

```
score = average POI rating
      + 0.4 if the route has 2-3 stops, 0.25 if 4+, 0.15 if 1
      + 0.05 per available photo, capped at 3 photos
      + 0.08 per distinct POI category
```

## Filtering the final set

Apply in order:

1. **Usable** — every stop has coordinates, no closed-venue keywords, and the average rating is
   at least 3.8.
2. **Relaxed** — same checks with an average rating of at least 3.5. Use only if fewer than three
   routes survive step 1.
3. **Last resort** — any route with at least one stop, used only to reach three options. Label
   these as lower confidence when presenting them.

## Deduplication

Two routes are duplicates when either is true:

- they visit the same POIs in the same order;
- they share both a near-identical title and the same first stop.

Normalise names before comparing: strip anything after `(` or `（`, trim whitespace, lowercase.
Keep the higher-scoring route.

## Diversity

Selecting the final 3–5 routes:

- Prefer a route that introduces a category no selected route has yet.
- Never let two routes start at the same first stop.
- Always keep at least three options when the candidates allow it, even if one is weaker; comparing
  options is the point of this skill.
