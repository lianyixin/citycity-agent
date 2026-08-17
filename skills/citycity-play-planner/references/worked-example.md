# Worked example

Request: 周六下午从静安寺出发，和朋友散步、喝咖啡，想要一条不累的路线

## 1. Intent

```yaml
target_area: 静安寺
departure: 静安寺
time_context: 周六下午
companions: 朋友
preference_tags: [散步, 咖啡, 拍照]
nearby_intent: true
hard_constraints: [不要走太远]
```

## 2. Location

```bash
python3 scripts/amap_poi.py geocode --address 静安寺 --city 上海
```

Take the first result's `location` (for example `121.4453,31.2237`) as the search center.

## 3. Planner fan-out

| Plan | Keywords | Category |
| --- | --- | --- |
| 静安寺咖啡漫步 | 咖啡馆 街区 静安寺 | restaurant |
| 静安梧桐拍照路线 | 老洋房 街区 拍照 | culture |
| 静安公园慢走 | 公园 散步 静安 | tourism |
| 静安小店逛街 | 买手店 商场 静安寺 | shopping |

Four distinct themes, all searchable, all local. A plan such as "感受静安氛围" would be rejected:
it cannot be used as a map query.

## 4. Execute in parallel

Each branch runs one search, up to four at a time:

```bash
python3 scripts/amap_poi.py search --keywords "咖啡馆 街区 静安寺" --location 121.4453,31.2237 --radius 5000 --limit 12
```

Outcomes:

- 咖啡漫步 → selected a 4.7-rated cafe about 600 m away.
- 拍照路线 → selected a historic block about 1.2 km away.
- 公园慢走 → selected 静安公园, 350 m away.
- 逛街 → no suitable POI; the candidates were large malls, which conflicts with 不累 and 散步.

The failed branch does not block the rest.

## 5. Expand

For the coffee branch, search around the selected cafe's coordinates:

```bash
python3 scripts/amap_poi.py search --keywords "本帮菜 餐厅" --location "<cafe lng,lat>" --radius 2000 --limit 12
```

The park branch gains a nearby dessert stop. Routes reach two to three stops each.

## 6. Filter

- All remaining routes have coordinates and no closed-venue keywords.
- Ratings average above 3.8, so the strict pass keeps them.
- No two routes share a first stop, and categories differ across routes.

## 7. Present

```markdown
周六下午从静安寺出发，给你三条不累的路线：

**1. 咖啡漫步 · 约 2.5 小时**
- 14:30 <咖啡馆>（<地址>｜评分 4.7｜距出发点 600 米）— 街区安静，适合边走边聊
- 16:30 <本帮菜馆>（<地址>｜人均 ¥90）— 步行 10 分钟，收尾吃饭

**2. 梧桐街区拍照 · 约 2 小时**
- ...

**3. 静安公园慢走 · 约 1.5 小时**
- ...

三条路线单程都在 1.5 公里内。营业时间和当天是否需要排队建议出发前再确认一下。
逛街方向这次没找到合适的地点：附近以大型商场为主，和你想要的"不累的散步"不太匹配。

完整版（含照片、地图链接、站间距离）：静安寺周六下午玩法.html
```

Text only. The POI photos are not embedded here — they belong on the page, and the chat reply
just links to it.

## 8. HTML page

First check for a design skill in the environment; if one is available, it drives the visual
layer. Otherwise design it yourself against
[references/html-page.md](html-page.md).

This plan is a slow, photo-friendly afternoon, so the page is designed to match: the warm
CityCity light palette, a serif display heading over a sans body, POI photos all cropped to 4:3
inside an 820px content column, and a vertical timeline carrying the walking distance between
stops. A nightlife plan for the same area would get a dark, neon-accented treatment instead — with
the same contrast discipline — and a two-stop date would read better as a side-by-side comparison.

Written by hand into `静安寺周六下午玩法.html`: one file, inline CSS, the user's original
question at the top, the three routes with real POI photos and coordinates, straight-line
distance between stops, the failed 逛街 direction, and a quiet note that opening hours were not
verified.

Then walk the self-review checklist — content column, type scale, contrast, photo crops, 375px
width — and fix what fails before handing the file over.
