# Designing the HTML page

You write this page yourself. There is no template and no renderer script, because a rainy-day
family plan and a late-night bar crawl should not look the same.

Design it the way a good editor would design that specific outing, then hand-write the HTML and
CSS to match. The page is the deliverable, and it is judged on craft as well as on accuracy.

## Delegate the visual layer when you can

Before writing any HTML, check whether the environment offers a skill about web design, visual
design, frontend aesthetics, or artifact/page building. If one exists, invoke it and follow it for
typography, colour, spacing, and layout. This document then serves as the content contract: what
must appear on the page and what must never be invented.

If no design skill is available, everything below is the standard you are held to.

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

## The craft bar

Every page must clear all of this, whatever visual direction you pick. These are the differences
between a designed page and a data dump, and they are not optional.

### Layout and spacing

- **Constrain the content column.** One centred container, `max-width` between 680px and 900px
  (up to 1100px only if you are genuinely using a multi-column grid). Text that runs the full
  width of a desktop window is the single most obvious tell of an unstyled page.
- **Keep real gutters.** At least 24px of horizontal padding on desktop, 20px on mobile. Nothing
  touches the edge of the viewport except a deliberate full-bleed hero image.
- **Use one spacing scale** and only its steps: 4, 8, 12, 16, 24, 32, 48, 64, 96. No arbitrary
  `margin: 13px`.
- **Give the page vertical rhythm.** Section gaps (48–96px) must be clearly larger than gaps
  inside a section (12–24px), so structure is visible before anything is read.
- **Build a hierarchy, not a list.** The hero, the route comparison, and the route detail are
  three different weights. Four identical cards in a row with identical type sizes tells the
  reader nothing about what matters.

### Typography

- **Set a type scale with real contrast**, roughly: hero 36–56px, section title 24–28px, stop name
  18–20px, body 15–16px, meta 13–14px. If almost all your text lands at 13–14px, the page will
  read as a dense grey slab.
- **Body text is never below 14px**, and captions never below 12px.
- **Line height** 1.6–1.75 for CJK body text, 1.15–1.25 for large headings.
- **Two font families at most**, with a CJK-safe stack:
  `system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif`.
  A serif display face for headings paired with a sans body works well; do not use a serif that
  has no CJK coverage for Chinese text.
- **CJK does not need letter-spacing.** Do not add tracking to Chinese body text. Slight negative
  tracking on large Latin display text is fine.
- **Limit line length** to about 38–46 CJK characters.

### Colour and contrast

- **Pick one accent colour** and use it for one job — the current stop, the route index, links.
  An accent used everywhere is not an accent.
- **Body text must pass 4.5:1** against its background; large headings at least 3:1. Check it.
  Gold or muted grey on near-black almost never passes: that is why the page looks murky.
- **Build the surface in three steps** — page background, card surface, border — with visible but
  restrained separation. Do not distinguish cards using heavy drop shadows alone.
- **Dark themes are harder.** If you choose one, use a lifted background (`#14131a`-ish, not pure
  black), a card surface a step lighter, borders at 8–12% white, body text at 80–90% white, and
  meta text no dimmer than 60%. If you cannot hold contrast, use a light theme.
- **Never place text directly on a POI photo** without a gradient scrim or a solid plate behind it.

### Photos

POI photos arrive at wildly different sizes and quality. Uncropped, they wreck the page.

- **Crop every photo to a consistent aspect ratio** — `aspect-ratio: 4 / 3` or `16 / 9` — with
  `object-fit: cover; width: 100%; display: block;`.
- **Round photo corners** to match the surrounding cards, and clip with `overflow: hidden`.
- **Give a grid of photos a real gap** (8–12px). Never butt two photos edge to edge.
- **Cap photo height** (roughly 240–320px) so one tall image cannot own the whole screen.
- **Add `loading="lazy"`** and an `alt` with the place name.
- **Design the missing-photo state**: a tinted block with the category name or an initial, sized
  to the same aspect ratio as the real photos.

### Components

- **Tags and pills** need `padding: 4px 10px`, a border radius, a subtle background, and 6–8px of
  gap. A bare row of bracketed words is not a tag row.
- **Cards** need consistent internal padding (16–24px), one radius value across the page, and
  equal heights within a row.
- **The unverified-data notice** is a quiet aside, not a warning banner competing with the hero.
  Small type, muted colour, placed near the routes it qualifies.
- **Links and map buttons** must look tappable: minimum 44px touch target, obvious affordance.

### Responsive

- Single column below 640px. Test the layout mentally at 375px width.
- No horizontal scrolling at any width. Long addresses wrap, they do not overflow.
- `<meta name="viewport" content="width=device-width, initial-scale=1">`.

### Restraint

- **No gratuitous motion.** At most a hover lift on cards and a colour transition. No entrance
  animations, no parallax, no auto-playing carousels.
- **No emoji as iconography.** Use inline SVG, a typographic mark, or nothing.
- **No gradients on text** unless the whole page's visual direction is built around it.
- Nothing on the page should exist only to look busy.

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
`#1d1b1a`, muted `#6c6661`, accent `#ff2e4d`, and rounded corners around 18–24px. This light
palette is the safe default; reach for a dark theme only when the plan is genuinely nocturnal and
you can hold the contrast rules above.

## Worth adding when the data supports it

- Per-route totals: walking distance, per-person cost range, number of stops.
- A comparison strip so the routes can be judged at a glance.
- Category tags on each stop, so the mix is visible.
- Print-friendly CSS.
- A small inline SVG showing relative stop positions, drawn from the actual coordinates.

Skip anything the data cannot support. An empty section is worse than no section.

## Self-review before you deliver

Read the file back and answer each of these. Fix anything that fails, then re-check.

**Truth**

- [ ] Every place, rating, price, and photo URL traces back to a search in this session.
- [ ] Straight-line distances are labelled as estimates.
- [ ] The unverified-hours notice is present and findable.
- [ ] The user's original question and the intent appear on the page.

**Craft**

- [ ] The content sits in a constrained, centred column — not edge to edge.
- [ ] Hero, section titles, stop names, body, and meta are visibly different sizes.
- [ ] Body text passes 4.5:1 contrast; no text sits directly on an unscrimmed photo.
- [ ] Every photo is cropped to the same aspect ratio, rounded, and gapped.
- [ ] Missing photos render as a designed placeholder, not a broken image.
- [ ] Section spacing is clearly larger than intra-section spacing.
- [ ] The accent colour appears on one kind of element, not everywhere.
- [ ] At 375px width: one column, no horizontal scroll, nothing clipped.

**Judgement**

- [ ] The visual direction matches this specific plan, and would look wrong for the opposite plan.
- [ ] There is a clear focal point, and it is the routes.
- [ ] Nothing on the page is decoration without information.
- [ ] You would send this page to a friend without apologising for it.

Then tell the user where the file is saved.
