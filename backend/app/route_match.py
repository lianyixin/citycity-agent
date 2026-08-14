"""将 POI 玩法分组与小红书正文中的路线/玩法/方案段落对齐。

匹配策略：先从正文段落抽取「地点候选短语」，再与 POI 名称做相似度打分，
按阈值过滤后按出现顺序输出。规则仅用于候选抽取与置信度加权，不做硬编码配对。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.xhs_content_format import is_section_title_line

_NUM = r"[一二三四五六七八九十百千万\dA-Za-z]+"
_CN_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_SECTION_HEADER_RE = re.compile(
    rf"^(?:.{{0,24}}?)?(?:【)?(?:玩法|路线|方案)({_NUM})(?:[：:]([^】\n]+))?】?(.*)$"
)
_MEANINGLESS_TITLE_RE = re.compile(
    r"(?:组合体验|主题体验|多元化体验|体验之旅|Tourism|Restaurant|Entertainment|Shopping|Culture|Sports|Other|Wellness|Nightlife|Outdoor)",
    re.IGNORECASE,
)
_STRICT_POI_SUFFIXES = ("历史文化名街",)
_TIPS_MARKERS = (
    "小贴士",
    "💡小贴士",
    "Tips",
    "tips",
    "温馨提示",
    "注意事项",
    "总结",
)

CandidateSource = Literal[
    "p_marker",
    "bracket",
    "arrow",
    "time_range",
    "numbered",
    "route_segment",
    "title",
    "area",
    "line",
]

_SOURCE_THRESHOLD: dict[CandidateSource, float] = {
    "p_marker": 0.52,
    "bracket": 0.55,
    "arrow": 0.58,
    "time_range": 0.58,
    "numbered": 0.60,
    "route_segment": 0.62,
    "title": 0.55,
    "area": 0.65,
    "line": 0.72,
}

_POI_TYPE_SUFFIXES = (
    "海鲜餐厅",
    "餐厅",
    "咖啡馆",
    "咖啡店",
    "咖啡",
    "书局",
    "书店",
    "酒吧",
    "居酒屋",
    "艺术空间",
    "纪念馆",
    "博物馆",
    "纪念地",
    "文化中心",
    "绿地",
    "公园",
    "家居",
    "商场",
    "体验馆",
    "欢乐世界",
)
_ACTION_PREFIXES = (
    "直接去",
    "直奔",
    "溜达到",
    "路线：",
    "路线:",
    "先去",
)
_P_SUFFIX_RE = re.compile(
    r"([^\n！!。→>+]{2,30})[（(][Pp]\s*\d+(?:\s*[,，/／\-—~～]\s*[Pp]?\s*\d+)?[）)]"
)
_PIN_BEFORE_P_RE = re.compile(
    r"📍?\s*([^（(\n→/]{2,40})[（(][Pp]\s*\d+"
)


@dataclass
class ContentSection:
    index: int
    kind: str
    label: str
    title: str
    text: str = ""


@dataclass
class MethodBucket:
    method_order: int
    places: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MatchedRouteGroup:
    section_index: int
    section_label: str
    title: str
    places: list[dict[str, Any]]


@dataclass
class LocationCandidate:
    text: str
    position: int
    source: CandidateSource


@dataclass
class _PlaceMatch:
    place: dict[str, Any]
    position: int
    score: float


def _cn_num_to_int(raw: str) -> int:
    token = raw.strip()
    if not token:
        return 0
    if token.isdigit():
        return int(token)
    if len(token) == 1 and token in _CN_DIGITS:
        return _CN_DIGITS[token]
    if token.startswith("十") and len(token) == 2 and token[1] in _CN_DIGITS:
        return 10 + _CN_DIGITS[token[1]]
    if token.endswith("十") and len(token) == 2 and token[0] in _CN_DIGITS:
        return _CN_DIGITS[token[0]] * 10
    return 0


def _clean_title(text: str) -> str:
    cleaned = re.sub(r"\*\*", "", text).strip()
    cleaned = re.sub(r"^[（(].*?[）)]", "", cleaned).strip()
    cleaned = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+", "", cleaned).strip()
    return cleaned


def _parse_section_header(line: str) -> tuple[str, str, str, str] | None:
    stripped = re.sub(r"\*\*", "", line.strip())
    if not is_section_title_line(stripped):
        return None
    match = _SECTION_HEADER_RE.match(stripped)
    if not match:
        return None

    num_raw, title_in_bracket, trailing = match.groups()
    kind_match = re.search(r"(玩法|路线|方案)", stripped)
    kind = kind_match.group(1) if kind_match else "路线"
    section_num = _cn_num_to_int(num_raw)
    if section_num <= 0:
        return None

    title = _clean_title(title_in_bracket or "")
    if not title:
        title = _clean_title(trailing)
    if not title:
        title = f"{kind}{num_raw}"

    label = f"{kind}{num_raw}"
    return kind, label, title, trailing or ""


def parse_content_sections(content: str) -> list[ContentSection]:
    if not content:
        return []

    sections: list[ContentSection] = []
    current: ContentSection | None = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        header = _parse_section_header(line)
        if header:
            if current is not None:
                current.text = "\n".join(current_lines).strip()
                sections.append(current)
            kind, label, title, trailing = header
            current = ContentSection(
                index=len(sections) + 1,
                kind=kind,
                label=label,
                title=title,
            )
            current_lines = [trailing] if trailing.strip() else []
            continue
        if current is not None:
            current_lines.append(line)

    if current is not None:
        current.text = "\n".join(current_lines).strip()
        sections.append(current)

    return sections


def _drop_tips_tail(text: str) -> str:
    earliest = len(text)
    for marker in _TIPS_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            earliest = min(earliest, idx)
    return text[:earliest].strip()


def _is_address_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("📍") or stripped.startswith("地址"):
        return True
    if re.search(r"[Pp]\s*\d+", stripped):
        return False
    if re.search(r"\d{1,2}:\d{2}", stripped) and re.search(r"(到|→|->)", stripped):
        return False
    if re.search(r"\d+号", stripped) and ("路" in stripped or "街" in stripped or "道" in stripped):
        return True
    if re.search(r"(地铁|公里|人均|营业时间|⏰|💰)", stripped):
        return True
    return False


def _clean_candidate_text(text: str) -> str:
    cleaned = re.sub(r"\*\*", "", text).strip()
    cleaned = re.sub(r"^[^\w\u4e00-\u9fff]+", "", cleaned)
    cleaned = re.sub(
        r"^(?:上午|下午|晚上|早上)?\d{1,2}[:：点半点]+(?:去|到|赶|冲|先)?\s*",
        "",
        cleaned,
    )
    for prefix in _ACTION_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    cleaned = re.sub(r"[（(][Pp]\s*\d+[^）)]*[）)]", "", cleaned)
    cleaned = re.sub(r"[（(].*$", "", cleaned)
    cleaned = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+", "", cleaned).strip()
    for sep in ("！", "!", "。", "？", "?", "；", ";"):
        if sep in cleaned:
            cleaned = cleaned.split(sep, 1)[0].strip()
    if len(cleaned) > 40:
        cleaned = cleaned[:40].strip()
    for suffix in (
        "吃早午餐",
        "吃早茶",
        "吃晚餐",
        "吃午餐",
        "吃夜宵",
        "骑行",
        "散步",
        "拍照",
        "打卡",
        "逛逛",
        "消食",
    ):
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix) + 2:
            cleaned = cleaned[: -len(suffix)].strip()
    return cleaned.strip(" ，,、-→>＋+")


def _normalize_name(text: str) -> str:
    normalized = re.sub(r"[\(（][^)）]*[\)）]", "", text)
    normalized = re.sub(r"[\s\-_·•]", "", normalized)
    normalized = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]", "", normalized)
    return normalized.lower()


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    if len(text) < n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _levenshtein_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    distance = prev[-1]
    return 1.0 - distance / max(len(a), len(b))


def _poi_name_variants(name: str) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip()
        if len(value) < 2 or value in seen:
            return
        seen.add(value)
        variants.append(value)

    add(name)
    no_paren = re.sub(r"\([^)]*\)", "", name).strip()
    add(no_paren)
    before_paren = name.split("(")[0].strip()
    add(before_paren)

    for match in re.finditer(r"[\(（]([^)）]+)[\)）]", name):
        inner = match.group(1).strip()
        add(inner)
        city = os.getenv("DEFAULT_CITY", "上海").strip() or "上海"
        if inner.startswith(city) and len(inner) > len(city) + 2:
            add(inner[len(city):])

    chinese = re.sub(r"[\(（][^)）]*[\)）]", "", name).strip()
    if chinese:
        add(chinese)
        city = os.getenv("DEFAULT_CITY", "上海").strip() or "上海"
        if chinese.startswith(city) and len(chinese) > len(city) + 2:
            add(chinese[len(city):])
        for suffix in _POI_TYPE_SUFFIXES:
            if suffix in chinese:
                prefix = chinese.split(suffix, 1)[0]
                if len(prefix) >= 3:
                    add(prefix)

    for match in re.finditer(r"[A-Za-z][A-Za-z0-9&.'\s-]*", name):
        add(match.group(0).strip())

    return variants


def _latin_tokens(text: str) -> list[str]:
    return [token.strip() for token in re.findall(r"[A-Za-z][A-Za-z0-9&.'\s-]*", text) if len(token.strip()) >= 3]


def _is_strict_poi(name: str) -> bool:
    chinese = re.sub(r"[\(（][^)）]*[\)）]", "", name).strip()
    return chinese.endswith(_STRICT_POI_SUFFIXES)


def _chinese_only(text: str) -> str:
    return re.sub(r"[^一-龥]", "", text)


def _chinese_overlap_score(candidate: str, poi_name: str) -> float:
    cand_cn = _chinese_only(candidate)
    poi_cn = _chinese_only(poi_name)
    if len(cand_cn) < 2 or len(poi_cn) < 2:
        return 0.0
    if cand_cn in poi_cn:
        return 0.92
    if poi_cn in cand_cn:
        return 0.88

    best_len = 0
    for size in range(len(cand_cn), 2, -1):
        for start in range(len(cand_cn) - size + 1):
            sub = cand_cn[start : start + size]
            if sub in poi_cn:
                best_len = max(best_len, size)
        if best_len >= 4:
            break

    if best_len >= 3:
        return 0.62 + (best_len / len(cand_cn)) * 0.33
    return 0.0


def score_candidate_vs_poi(candidate: str, poi_name: str) -> float:
    """候选短语与 POI 名称的相似度，0~1。"""
    cand = _clean_candidate_text(candidate)
    if not cand or not poi_name:
        return 0.0

    poi_variants = _poi_name_variants(poi_name)
    cand_norm = _normalize_name(cand)
    best = 0.0

    for variant in poi_variants:
        variant_norm = _normalize_name(variant)
        if not variant_norm:
            continue

        if cand_norm == variant_norm:
            return 1.0
        if len(cand_norm) >= 3 and cand_norm in variant_norm:
            best = max(best, 0.95)
        if len(variant_norm) >= 3 and variant_norm in cand_norm:
            best = max(best, 0.90)

        best = max(best, _jaccard(_char_ngrams(cand_norm), _char_ngrams(variant_norm)))
        if len(cand_norm) <= 20 and len(variant_norm) <= 30:
            best = max(best, _levenshtein_ratio(cand_norm, variant_norm))

    cand_latin = _latin_tokens(cand)
    poi_latin = _latin_tokens(poi_name)
    if cand_latin and poi_latin:
        for ct in cand_latin:
            for pt in poi_latin:
                if ct.lower() == pt.lower():
                    best = max(best, 0.95)
                elif ct.lower() in pt.lower() or pt.lower() in ct.lower():
                    best = max(best, 0.85)

    best = max(best, _chinese_overlap_score(cand, poi_name))

    if _is_strict_poi(poi_name):
        chinese = re.sub(r"[\(（][^)）]*[\)）]", "", poi_name).strip()
        if chinese not in cand and cand not in chinese:
            if best < 0.85:
                return 0.0

    return best


def _is_noise_candidate(text: str) -> bool:
    if not text:
        return True
    if re.search(r"(方案|路线|玩法)[一二三四五六七八九十\d]", text):
        return True
    if text in {"行程顺序", "推荐理由", "适合"}:
        return True
    if "→" in text or "->" in text:
        return True
    if re.match(r"^[Pp]\d+", text):
        return True
    return False


def _resolve_line_position(offset: int, line: str, raw_text: str) -> int:
    """把候选短语映射到行内真实起始位置，便于按正文顺序排序。"""
    cleaned = _clean_candidate_text(raw_text)
    if cleaned:
        idx = line.find(cleaned)
        if idx >= 0:
            return offset + idx
    stripped = raw_text.strip()
    if stripped:
        idx = line.find(stripped)
        if idx >= 0:
            return offset + idx
    return offset


def _add_candidate(
    candidates: list[LocationCandidate],
    text: str,
    position: int,
    source: CandidateSource,
) -> None:
    cleaned = _clean_candidate_text(text)
    if len(cleaned) < 2 or _is_noise_candidate(cleaned):
        return
    if re.fullmatch(r"[Pp]\s*\d+(?:\s*[-—~～]\s*[Pp]?\s*\d+)?", cleaned):
        return
    candidates.append(LocationCandidate(text=cleaned, position=position, source=source))


def extract_location_candidates(section_text: str) -> list[LocationCandidate]:
    """从方案段落正文中抽取地点候选短语。"""
    candidates: list[LocationCandidate] = []
    offset = 0

    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped:
            offset += len(line) + 1
            continue

        for match in re.finditer(
            r"[Pp]\s*\d+(?:\s*[-—~～]\s*[Pp]?\s*\d+)?\s+([^\n（(]+)",
            stripped,
        ):
            _add_candidate(
                candidates,
                match.group(1),
                _resolve_line_position(offset, stripped, match.group(1)),
                "p_marker",
            )

        for match in _PIN_BEFORE_P_RE.finditer(stripped):
            _add_candidate(
                candidates,
                match.group(1),
                _resolve_line_position(offset, stripped, match.group(1)),
                "p_marker",
            )

        for match in _P_SUFFIX_RE.finditer(stripped):
            _add_candidate(
                candidates,
                match.group(1),
                _resolve_line_position(offset, stripped, match.group(1)),
                "p_marker",
            )

        for match in re.finditer(r"【([^】]{2,40})】", stripped):
            _add_candidate(candidates, match.group(1), offset + match.start(), "bracket")

        pin_colon = re.match(r"^📍\s*([^：:\n（(]{2,30})[：:]", stripped)
        if pin_colon:
            _add_candidate(
                candidates,
                pin_colon.group(1),
                _resolve_line_position(offset, stripped, pin_colon.group(1)),
                "p_marker",
            )

        if _is_address_line(stripped):
            offset += len(line) + 1
            continue

        for match in re.finditer(
            r"(?:步行\d+米到|前往|到达)\s*([^\n→>＋+（(]{2,40})",
            stripped,
        ):
            _add_candidate(candidates, match.group(1), offset + match.start(), "arrow")

        for match in re.finditer(
            r"在([^，,。！!？?；;→>~～\s]{2,12})(?:附近|旁)?[，,！!]",
            stripped,
        ):
            _add_candidate(
                candidates,
                match.group(1),
                _resolve_line_position(offset, stripped, match.group(1)),
                "area",
            )

        for match in re.finditer(
            r"\d{1,2}:\d{2}(?:-\d{1,2}:\d{2})?\s+([^\n（(]{2,40})",
            stripped,
        ):
            fragment = re.sub(r"^步行\d+米到", "", match.group(1)).strip()
            _add_candidate(candidates, fragment, offset + match.start(), "time_range")

        for match in re.finditer(r"(\d)️⃣\s*([^+＋\n（(]{2,40})", stripped):
            _add_candidate(candidates, match.group(2), offset + match.start(), "numbered")

        if "->" in stripped or "→" in stripped:
            for segment in re.split(r"\s*(?:->|→)\s*", stripped):
                segment = re.sub(r"^[行程顺序：:\s]+", "", segment)
                segment = re.sub(r"[（(][Pp]\s*\d+[^）)]*[）)]", "", segment)
                segment = re.sub(r"[（(].*$", "", segment).strip()
                if segment and len(segment) >= 2 and not _is_noise_candidate(segment):
                    _add_candidate(
                        candidates,
                        segment,
                        _resolve_line_position(offset, stripped, segment),
                        "route_segment",
                    )

        body = re.sub(r"^[Pp]\s*\d+(?:\s*[-—~～]\s*[Pp]?\s*\d+)?\s*", "", stripped)
        body = re.sub(r"^[行程顺序：:\s]+", "", body)
        if (
            body
            and not re.match(r"^(推荐理由|适合|下午|晚上|早上)", body)
            and not _is_noise_candidate(body)
            and "->" not in body
            and "→" not in body
        ):
            _add_candidate(candidates, body, offset, "line")

        offset += len(line) + 1

    deduped: list[LocationCandidate] = []
    seen: set[tuple[str, int]] = set()
    for candidate in sorted(candidates, key=lambda item: (item.position, item.source)):
        if _is_noise_candidate(candidate.text):
            continue
        key = (candidate.text, candidate.position // 20)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _best_poi_for_candidate(
    candidate: LocationCandidate,
    places: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    threshold = _SOURCE_THRESHOLD[candidate.source]
    best_place: dict[str, Any] | None = None
    best_score = 0.0
    for place in places:
        name = str(place.get("name") or "")
        score = score_candidate_vs_poi(candidate.text, name)
        if score >= threshold and score > best_score:
            best_place = place
            best_score = score
    return best_place, best_score


def _section_title_candidates(section: ContentSection) -> list[LocationCandidate]:
    """方案标题里常直接出现店名/品牌名，如「乐玩陶艺DIY」「GREEN & SAFE早午餐」。"""
    if not section.title:
        return []
    cleaned = _clean_candidate_text(section.title)
    if len(cleaned) < 2 or _is_noise_candidate(cleaned):
        return []
    return [LocationCandidate(text=cleaned, position=0, source="title")]


def _places_for_section(
    section: ContentSection,
    places: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    section_body = _drop_tips_tail(section.text)
    unique_places = _unique_places(places)
    candidates = _section_title_candidates(section) + extract_location_candidates(section_body)

    matches: list[_PlaceMatch] = []
    used_keys: set[str] = set()

    for candidate in candidates:
        place, score = _best_poi_for_candidate(candidate, unique_places)
        if place is None:
            continue
        key = str(place.get("amap_poi_id") or place.get("name") or "")
        if not key or key in used_keys:
            continue
        used_keys.add(key)
        matches.append(_PlaceMatch(place=place, position=candidate.position, score=score))

    matches.sort(key=lambda item: item.position)
    return [item.place for item in matches]


def poi_mention_position(poi_name: str, text: str) -> int:
    if not poi_name or not text:
        return 10**9
    candidates = extract_location_candidates(text)
    best_pos = 10**9
    for candidate in candidates:
        if score_candidate_vs_poi(candidate.text, poi_name) >= _SOURCE_THRESHOLD[candidate.source]:
            best_pos = min(best_pos, candidate.position)
    return best_pos


def sort_places_by_section_text(
    places: list[dict[str, Any]],
    section_text: str,
) -> list[dict[str, Any]]:
    order = {
        str(place.get("amap_poi_id") or place.get("name") or ""): poi_mention_position(
            str(place.get("name") or ""),
            section_text,
        )
        for place in places
    }
    return sorted(
        places,
        key=lambda place: (
            order.get(str(place.get("amap_poi_id") or place.get("name") or ""), 10**9),
            int(place.get("step_order") or 0),
        ),
    )


def poi_mentioned_in_text(poi_name: str, text: str) -> bool:
    return poi_mention_position(poi_name, text) < 10**9


def _unique_places(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for place in places:
        key = str(place.get("amap_poi_id") or place.get("name") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(place)
    return unique


def _group_places_by_method(places: list[dict[str, Any]]) -> list[MethodBucket]:
    buckets: dict[int, MethodBucket] = {}
    for place in places:
        order = int(place.get("method_order") or 0)
        if order <= 0:
            order = len(buckets) + 1
        if order not in buckets:
            buckets[order] = MethodBucket(method_order=order)
        buckets[order].places.append(place)
    return [buckets[k] for k in sorted(buckets)]


def _is_meaningless_title(title: str | None) -> bool:
    if not title:
        return True
    return bool(_MEANINGLESS_TITLE_RE.search(title))


def match_routes_to_content(
    content: str,
    places: list[dict[str, Any]],
    *,
    min_overlap: int = 1,
) -> list[MatchedRouteGroup]:
    """按正文段落顺序，将 POI 与内容中的路线/玩法/方案对齐。"""
    if not places:
        return []

    sections = parse_content_sections(content)
    buckets = _group_places_by_method(places)

    if not sections:
        if len(buckets) == 1:
            bucket = buckets[0]
            title = bucket.places[0].get("method_title") if bucket.places else ""
            if _is_meaningless_title(str(title or "")):
                title = "推荐路线"
            return [
                MatchedRouteGroup(
                    section_index=1,
                    section_label="路线",
                    title=str(title or "推荐路线"),
                    places=sort_places_by_section_text(bucket.places, content),
                )
            ]
        return []

    matched: list[MatchedRouteGroup] = []

    for section in sections:
        section_places = _places_for_section(section, places)
        if len(section_places) < min_overlap:
            continue

        matched.append(
            MatchedRouteGroup(
                section_index=section.index,
                section_label=section.label,
                title=section.title,
                places=section_places,
            )
        )

    return matched


def route_groups_payload(content: str, places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = match_routes_to_content(content, places)
    return [
        {
            "section_index": group.section_index,
            "section_label": group.section_label,
            "title": group.title,
            "places": group.places,
        }
        for group in groups
    ]
