---
name: citycity-play-planner
description: Plans several grounded city activity routes for a few hours to one day, using a Planner that fans out diverse ideas and parallel Execute branches that verify each stop against real Amap POI data. Use when the user asks what to do in a city, where to go tonight or this weekend, or wants a citywalk, date, family outing, food trip, photo route, or nightlife plan (e.g. "上海长宁今晚有什么好玩的", "周末下午想散步喝咖啡", "带孩子去哪玩"). Not for multi-day itineraries, hotels, or long-distance transport.
license: MIT
compatibility: Requires python3 and network access. POI grounding uses the Amap Web Service API, so an AMAP_API_KEY environment variable is required and coverage is limited to mainland China.
metadata:
  author: citycity-agent
  version: "1.0.0"
  source: https://github.com/lianyixin/citycity-agent
---

# CityCity Play Planner

Answer "what can I do here, and how" with several distinct routes, each grounded in real places.

Do not answer city activity questions from memory. Every recommended place must come from a live
POI search performed during this session.

## When to use

Use for a few hours, a half day, or one day of citywalks, dates, family outings, food trips,
photo routes, and nightlife.

Do not use for multi-day itineraries, hotel selection, flights, or inter-city transport. If the
request is multi-day, plan only one day with this skill and say the rest is out of scope.

## Requirements

- `python3` and network access.
- `AMAP_API_KEY` set in the environment. Without it, stop and ask the user for a key rather than
  inventing places.
- Amap covers mainland China. For other regions, tell the user this skill cannot ground results
  there.

Optional, but strongly recommended. Unlike a browser, an agent cannot read the user's GPS
position, so give it a home base once instead of answering "which city?" every time:

```bash
export DEFAULT_CITY=上海
export DEFAULT_CITY_LAT=31.2304
export DEFAULT_CITY_LNG=121.4737
```

Suggest these to the user the first time a request has no usable location.

## Workflow

```
1. Extract intent
2. Resolve the location
3. Planner: fan out 3-6 diverse plans
4. Execute: search and select a real POI per branch, in parallel
5. Expand: add the next stop to promising branches
6. Filter: drop weak routes, deduplicate, keep variety
7. Present: several routes the user can compare
```

### Step 1: Extract intent

Read the request and record:

| Field | Meaning |
| --- | --- |
| `target_area` | Where the user wants to play (district, landmark, business area) |
| `departure` | Where they start from, if different from `target_area` |
| `time_context` | 今晚 / 周六下午 / 下班后, and rough duration |
| `companions` | 一个人 / 朋友 / 情侣 / 亲子 / 家人 |
| `budget` | Total or per-person budget, if stated |
| `preference_tags` | 拍照 / 美食 / 咖啡 / 安静 / 夜景 / 室内 |
| `nearby_intent` | True when the request says 附近 / 周边 / 就近 / 离我最近 |
| `hard_constraints` | 雨天室内 / 无障碍 / 带宠物 / 地点不要分散 |

Rules:

- `target_area` outranks `departure`. Use `departure` only to reason about how the user gets there.
- When `nearby_intent` is true, keep everything within roughly 3–5 km of the departure point and
  do not propose cross-district landmarks.
- Do not infer a city from the user's language, timezone, or earlier unrelated chat.

### Step 2: Resolve the location

You have no access to the user's device location. Resolve the search center in this order and
stop at the first hit:

1. **Coordinates in the request** — use them directly.
2. **A place named in the request** (区, 商圈, 地标, 地铁站) — geocode it.
3. **A location the user gave earlier in this conversation** — reuse it, and say which one you
   are using.
4. **`DEFAULT_CITY_LAT` / `DEFAULT_CITY_LNG`** — use as the center, with `DEFAULT_CITY` as the
   city name.
5. **`DEFAULT_CITY` only** — search city-wide without a center. Say the results are city-wide, and
   do not claim anything is "nearby".
6. **Nothing** — ask the user. This is the one question worth asking.

```bash
python3 scripts/amap_poi.py geocode --address "静安寺" --city "上海"
```

Use the returned `lat` / `lng` as the search center. When `--city` is omitted, the script falls
back to `DEFAULT_CITY`.

When you must ask, keep it to one short question and offer the durable fix:

```text
你在哪个城市、从哪里出发？给个区、商圈或地铁站就行。
（也可以设置 DEFAULT_CITY / DEFAULT_CITY_LAT / DEFAULT_CITY_LNG，之后我就不用每次都问了。）
```

A 附近 request with no resolvable center cannot be answered. Ask instead of silently planning
around a city center — and never invent a location.

### Step 3: Planner — fan out

Produce 3–6 plans that differ in *theme*, not in wording. Each plan is a direction to explore,
never a specific venue: the Planner does not choose places.

Each plan needs:

```yaml
title: 静安寺咖啡漫步
description: 适合慢节奏、边走边拍的下午
keywords: [咖啡, 街区, 静安寺]     # must work as map search terms
category: restaurant|entertainment|shopping|tourism|sports|culture|nightlife|outdoor|wellness|other
suitable_start_time: 周六下午
duration_minutes: 90
```

Reject a plan when it duplicates another plan's theme, when its keywords are too abstract to
search (`浪漫氛围`), or when it ignores `target_area`, `nearby_intent`, weather, or companions.

### Step 4: Execute — ground each branch

Run branches concurrently, at most 4 at a time. Each branch owns one plan and one search.

```bash
python3 scripts/amap_poi.py search \
  --keywords "咖啡 街区 静安寺" \
  --location "121.4453,31.2237" \
  --city "上海" \
  --radius 5000 \
  --limit 12
```

Use the first three keywords as the query. Then select exactly one POI per branch using
[references/route-quality.md](references/route-quality.md).

Branch outcomes:

- **selected** — record the POI, why it fits, and an estimated duration.
- **no suitable POI** — record the reason and stop this branch. Do not force a weak match.
- **search failed** — record the error and stop this branch.

One failed branch never discards the others. Only when every branch fails do you report failure
instead of a plan.

### Step 5: Expand promising branches

For branches that found a good stop, add 0–2 next stops, up to 3 stops per route. Search around
the previous stop's coordinates so the route stays walkable:

```bash
python3 scripts/amap_poi.py search --keywords "本帮菜 餐厅" --location "<previous POI lng,lat>" --radius 2000 --limit 12
```

Prefer a next stop that adds a new category (walk → coffee → dinner) and stays within a few
kilometres. Stop expanding when the time budget is used up or nothing nearby fits.

### Step 6: Filter and diversify

Apply [references/route-quality.md](references/route-quality.md) to drop unusable routes,
deduplicate near-identical ones, and keep the final set varied. Aim for 3–5 routes; never present
several routes that visit the same first stop.

### Step 7: Present the routes

Reply in the user's language. Lead with a one-line read of their request, then the routes:

```markdown
今晚长宁，给你三条不同风格的路线：

**1. 咖啡漫步 · 约 2.5 小时**
- 19:00 <地点名>（<地址>｜评分 4.6）— 为什么适合：<一句话>
- 20:00 <地点名>（<地址>｜人均 ¥80）— 为什么适合：<一句话>
- 路线说明：两站相距约 900 米，步行 12 分钟

**2. ...**
```

Rules for the final answer:

- Only mention places returned by the search. Never invent a venue, address, or rating.
- Report ratings, per-person cost, and distance only when the search returned them.
- Do not state opening hours or prices that the data did not provide. Say they should be checked
  before going.
- Say which routes are weaker and why, instead of silently padding the list.
- If a branch failed, briefly say what could not be covered.

## Constraints

| Setting | Default |
| --- | --- |
| Root plans | 3–6 |
| Concurrent branches | 4 |
| Stops per route | 1–3 |
| Expansion rounds | 3 |
| Search radius | 5000 m (2000 m when expanding from a previous stop) |
| Candidates per search | 12 |
| Final routes | 3–5 |

## Fallbacks

- Planner output unusable: fall back to three template directions — 拍照打卡, 美食休息,
  城市散步 — built from `target_area` and `preference_tags`.
- Selection is ambiguous: pick the candidate with the best rating, then the one with photos.
- No candidate is acceptable: mark the branch as no-suitable-POI rather than lowering the bar.
- `AMAP_API_KEY` missing or the API rejects the key: stop and report it. Do not answer from
  memory.
- Location unresolvable: ask once for a starting point instead of guessing a city.

## Anti-patterns

- Recommending a place that no search returned.
- Letting the Planner pick venues, or letting Execute invent new themes.
- Returning one itinerary when the user asked what to do — the point is comparable options.
- Sending a 附近 request to a famous cross-district landmark.
- Assuming the user's city, or treating city-wide results as if they were nearby.
- Presenting LLM-written opening hours, prices, or transport times as verified facts.

## Reference

- [references/route-quality.md](references/route-quality.md) — POI selection, filtering,
  deduplication, and diversity rules.
- [references/worked-example.md](references/worked-example.md) — a full run from request to
  final routes.
