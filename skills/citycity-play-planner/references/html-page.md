# Designing the HTML page

You write this page yourself. There is no template and no renderer script, because a rainy-day
family plan and a late-night bar crawl should not look the same.

Design it the way a good editor would design that specific outing, then hand-write the HTML and
CSS to match.

## Non-negotiables

These are about truth and usability, not style.

1. **One self-contained `.html` file.** Inline CSS in a `<style>` tag. No build step, no local
   assets, no framework install. A CDN link is acceptable only if the page still reads fine when
   it fails to load.
2. **Only real data.** Every place name, address, rating, price, photo URL, and coordinate must
   come from this session's Amap results. If a field is missing, omit it — never fill the gap
   with a plausible-looking value.
3. **Photos come from the POI response.** Handle missing photos with a designed empty state, not
   a broken image and not a stock photo from elsewhere.
4. **Say what is unverified.** Opening hours, queues, and whether a place is open tonight were not
   checked. Put that somewhere visible, not buried.
5. **Readable on a phone.** Most people open this on the way out the door.
6. **`<html lang="zh-CN">`** and `<meta charset="utf-8">` for Chinese content.

## Content the page must carry

- The user's original question, quoted as they wrote it.
- The intent you worked from: area, time, companions, budget, preferences, hard constraints.
- The search center and city, so "附近" is verifiable.
- Every route: title, rough duration, and why it differs from the others.
- Every stop: name, address, category, rating and per-person cost when returned, photo, your
  one-line reason for choosing it, and a link that opens it in a map.
- Distance and rough walking time between consecutive stops, computed from coordinates.
- Directions that failed, and why.
- Generation time.

Straight-line distance from coordinates is an estimate. Label it as one.

Map link format: `https://uri.amap.com/marker?position=<lng>,<lat>&name=<name>`

## Design for this plan, not for all plans

Read the routes, then choose a visual direction that matches them:

| Plan | Direction that tends to work |
| --- | --- |
| 夜游 / 酒吧 | 深色背景、霓虹高亮、发光的时间线 |
| 亲子 / 雨天室内 | 明亮圆润、大图、清楚的室内标记 |
| 拍照 / Citywalk | 大图排版、留白、杂志感 |
| 美食 | 暖色、突出人均和菜系标签 |
| 约会 | 克制的双栏，强调两站之间怎么走 |

Vary the structure too, not just the palette: a two-stop date can be a side-by-side comparison,
while a four-stop citywalk reads better as a vertical timeline. Multiple routes are easier to
compare as cards side by side than as one long scroll.

Use the CityCity palette when nothing else fits: background `#f4f1ec`, surface `#fffdf9`, ink
`#1d1b1a`, muted `#6c6661`, accent `#ff2e4d`, and rounded corners around 18–24px.

## Worth adding when the data supports it

- Per-route totals: walking distance, per-person cost range, number of stops.
- A comparison strip so the routes can be judged at a glance.
- Category tags on each stop, so the mix is visible.
- Print-friendly CSS.
- A small inline SVG showing relative stop positions, drawn from the actual coordinates.

Skip anything the data cannot support. An empty section is worse than no section.

## Before you deliver

- Open the file and read it as the user would.
- Check that no place, rating, or photo appeared that the searches did not return.
- Check that it holds together at phone width.
- Tell the user where the file is saved.
