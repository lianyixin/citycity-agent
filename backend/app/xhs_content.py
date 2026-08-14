import json
import os
import re
from typing import Any

from app.agent_models import PlayMethod, PlayStep
from app.deepseek_client import DeepSeekClient
from app.xhs_content_format import format_xhs_content


_P_REF = re.compile(r"([Pp])\s*(\d{1,2})")


def _default_city() -> str:
    return os.getenv("DEFAULT_CITY", "上海").strip() or "上海"


class XHSContentGenerator:
    def __init__(self, deepseek_client: DeepSeekClient):
        self.deepseek = deepseek_client

    async def generate(
        self,
        query: str,
        methods: list[PlayMethod],
        location_name: str | None = None,
    ) -> dict[str, Any]:
        methods_info = _build_methods_info(methods[:4])
        image_urls = _collect_images(methods)
        system_prompt = _system_prompt()
        user_prompt = _user_prompt(query, methods_info, len(image_urls), location_name)
        response = await self.deepseek.chat_completion(
            prompt=user_prompt,
            system_message=system_prompt,
            temperature=0.8,
            max_tokens=2000,
        )
        content_json = _parse_json_object(response)
        city = _default_city()
        title = _normalize_title(str(content_json.get("title") or f"{city}玩法").strip(), query)
        content = format_xhs_content(str(content_json.get("content") or "").strip())
        tags = content_json.get("tags") if isinstance(content_json.get("tags"), list) else []
        normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        if city not in normalized_tags:
            normalized_tags.insert(0, city)
        fallback = format_xhs_content(_fallback_content(query, methods))
        return {
            "title": title,
            "content": content or fallback,
            "tags": normalized_tags[:12] or [city, "城市玩法"],
            "images": image_urls,
            "methods_info": methods_info,
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
        }

    async def generate_many(
        self,
        query: str,
        methods: list[PlayMethod],
        location_name: str | None = None,
        min_cards: int = 2,
        max_cards: int = 4,
    ) -> list[dict[str, Any]]:
        if not methods:
            return []
        methods_info = _build_methods_info(methods)
        image_urls = _collect_images(methods)
        response = await self.deepseek.chat_completion(
            prompt=_multi_user_prompt(query, methods_info, len(image_urls), location_name, min_cards, max_cards),
            system_message=_multi_system_prompt(),
            temperature=0.82,
            max_tokens=3600,
        )
        data = _parse_json_object(response)
        cards = data.get("cards") if isinstance(data.get("cards"), list) else []
        normalized: list[dict[str, Any]] = []
        for card in cards[:max_cards]:
            if not isinstance(card, dict):
                continue
            city = _default_city()
            title = _normalize_title(str(card.get("title") or f"{city}玩法").strip(), query)
            content = format_xhs_content(str(card.get("content") or "").strip())
            tags = card.get("tags") if isinstance(card.get("tags"), list) else []
            normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
            if city not in normalized_tags:
                normalized_tags.insert(0, city)
            normalized.append(
                {
                    "title": title,
                    "content": content,
                    "tags": normalized_tags[:12] or [city, "城市玩法"],
                    "images": image_urls,
                    "methods_info": methods_info,
                }
            )
        if len(normalized) >= min_cards:
            return normalized
        single = await self.generate(query, methods, location_name)
        return [single]

    async def generate_multi_route_note(
        self,
        query: str,
        methods: list[PlayMethod],
        location_name: str | None = None,
    ) -> dict[str, Any]:
        """把所有候选玩法汇总成一篇多方案小红书笔记。"""
        if not methods:
            raise ValueError("methods is required")

        candidate_images = _collect_candidate_images(methods)
        candidate_methods_info = _build_methods_info(methods, candidate_images)
        selection_json = await self._select_routes_for_note(query, candidate_methods_info, location_name)
        selected_indexes = _selected_method_indexes(selection_json, len(methods))
        selected_methods = [methods[index - 1] for index in selected_indexes]
        selected_methods = _methods_by_declared_order(selected_methods, selection_json.get("selected_routes"))

        selected_images = _collect_candidate_images(selected_methods)
        selected_methods_info = _build_methods_info(selected_methods, selected_images)
        content_json = await self._compose_note_content(
            query,
            selected_methods_info,
            len(selected_images),
            location_name,
        )
        city = _default_city()
        title = _normalize_title(str(content_json.get("title") or f"{city}玩法").strip(), query)
        content = format_xhs_content(str(content_json.get("content") or "").strip())
        if _max_p_reference(content) > len(selected_images):
            content = _remap_content_p_numbers(content, candidate_images, selected_images)
        tags = content_json.get("tags") if isinstance(content_json.get("tags"), list) else []
        normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        if city not in normalized_tags:
            normalized_tags.insert(0, city)
        fallback = format_xhs_content(_fallback_content(query, selected_methods))
        return {
            "title": title,
            "content": content or fallback,
            "tags": normalized_tags[:12] or [city, "城市玩法"],
            "images": selected_images,
            "selected_method_indexes": selected_indexes,
            "selected_methods": selected_methods,
            "methods_info": selected_methods_info,
            "user_prompt": _selected_routes_user_prompt(query, selected_methods_info, len(selected_images), location_name),
            "system_prompt": _content_only_system_prompt(),
        }

    async def _select_routes_for_note(
        self,
        query: str,
        candidate_methods_info: str,
        location_name: str | None,
    ) -> dict[str, Any]:
        response = await self.deepseek.chat_completion(
            prompt=_selection_user_prompt(query, candidate_methods_info, location_name),
            system_message=_selection_system_prompt(),
            temperature=0.35,
            max_tokens=1200,
        )
        return _parse_json_object(response)

    async def _compose_note_content(
        self,
        query: str,
        selected_methods_info: str,
        image_count: int,
        location_name: str | None,
    ) -> dict[str, Any]:
        response = await self.deepseek.chat_completion(
            prompt=_selected_routes_user_prompt(query, selected_methods_info, image_count, location_name),
            system_message=_content_only_system_prompt(),
            temperature=0.78,
            max_tokens=2600,
        )
        return _parse_json_object(response)


def _build_methods_info(methods: list[PlayMethod], images: list[str] | None = None) -> str:
    image_lookup = {url: index for index, url in enumerate(images or _collect_candidate_images(methods), start=1)}
    parts: list[str] = []
    for index, method in enumerate(methods, start=1):
        parts.append(f"【方案{index}】")
        parts.append(f"主题: {method.title}")
        parts.append(f"描述: {method.description}")
        parts.append(f"总时长: {method.total_duration_minutes}分钟")
        parts.append(f"综合评分: {method.rating}分")
        parts.append("")
        for step in method.steps:
            image_mark = _image_mark_for_poi(step.poi.photos, image_lookup)
            prefix = f"  {step.step_number}. "
            if image_mark:
                prefix += f"[图片{image_mark}] "
            parts.append(f"{prefix}{step.poi.name}")
            parts.append(f"     预计开始时间: {step.estimated_start_time or '灵活'}")
            parts.append(f"     停留时长: {step.duration_minutes}分钟")
            parts.append(f"     活动: {step.description}")
            parts.append(f"     地址: {step.poi.address}")
            parts.append(f"     评分: {step.poi.rating}分")
            if step.recommendation_reason:
                parts.append(f"     亮点: {step.recommendation_reason}")
            if step.poi.opening_hours:
                parts.append(f"     营业时间: {step.poi.opening_hours}")
            if step.poi.cost_per_person:
                parts.append(f"     人均消费: ¥{step.poi.cost_per_person}")
            parts.append("")
    return "\n".join(parts)


def _collect_images(methods: list[PlayMethod]) -> list[str]:
    images: list[str] = []
    for method in methods:
        for step in method.steps:
            for photo in step.poi.photos:
                if photo and photo not in images:
                    images.append(photo)
    return images


def _collect_candidate_images(methods: list[PlayMethod]) -> list[str]:
    images: list[str] = []
    for method in methods:
        for step in method.steps:
            for photo in step.poi.photos[:2]:
                if photo and photo not in images:
                    images.append(photo)
    return images


def _image_mark_for_poi(photos: list[str], image_lookup: dict[str, int]) -> str:
    marks: list[str] = []
    for photo in photos[:2]:
        index = image_lookup.get(photo)
        if index:
            marks.append(f"P{index}")
    return "/".join(marks)


def _parse_json_object(response: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("No JSON object found", response, 0)
    return json.loads(match.group())


def _normalize_title(title: str, query: str) -> str:
    title = re.sub(r"（?方案\d+）?", "", title).strip(" -：:")
    dull_suffixes = ("一日游", "半日游", "玩法", "攻略")
    is_short_dull = len(title) <= 8 and any(title.endswith(suffix) for suffix in dull_suffixes)
    if not title or is_short_dull:
        title = _fallback_title(query)
    return title[:30]


def _fallback_title(query: str) -> str:
    compact = re.sub(r"\s+", "", query)
    area_match = re.search(r"去([^玩]+)玩|在([^玩]+)玩", compact)
    area = next((group for group in (area_match.groups() if area_match else []) if group), "")
    area = area[:4] or _default_city()
    if any(token in compact for token in ("好友", "朋友", "聚会", "闺蜜")):
        return f"{area}聚会攻略：几种玩法任你选"
    if any(token in compact for token in ("娃", "亲子", "小朋友", "孩子")):
        return f"{area}遛娃路线｜轻松玩一整天"
    if any(token in compact for token in ("老婆", "情侣", "约会")):
        return f"{area}约会路线｜慢慢逛也浪漫"
    return f"{area}出游攻略｜照着走不费脑"


def _selected_method_indexes(content_json: dict[str, Any], method_count: int) -> list[int]:
    raw = content_json.get("selected_method_indexes")
    indexes: list[int] = []
    if isinstance(raw, list):
        for item in raw:
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= index <= method_count and index not in indexes:
                indexes.append(index)
    if indexes:
        return indexes[:4]
    return list(range(1, min(method_count, 4) + 1))


def _methods_by_declared_order(methods: list[PlayMethod], raw_routes: Any) -> list[PlayMethod]:
    if not isinstance(raw_routes, list):
        return methods
    routes_by_index: dict[int, list[str]] = {}
    for route in raw_routes:
        if not isinstance(route, dict):
            continue
        try:
            method_index = int(route.get("method_index"))
        except (TypeError, ValueError):
            continue
        poi_names = route.get("poi_names")
        if isinstance(poi_names, list):
            routes_by_index[method_index] = [str(name).strip() for name in poi_names if str(name).strip()]

    reordered: list[PlayMethod] = []
    for output_index, method in enumerate(methods, start=1):
        ordered_names = routes_by_index.get(output_index)
        if not ordered_names:
            reordered.append(method)
            continue
        reordered.append(method.model_copy(update={"steps": _steps_by_declared_order(method, ordered_names)}))
    return reordered


def _steps_by_declared_order(method: PlayMethod, ordered_names: list[str]) -> list[PlayStep]:
    remaining = method.steps.copy()
    ordered: list[PlayStep] = []
    for name in ordered_names:
        match = next((step for step in remaining if _same_poi_name(step.poi.name, name)), None)
        if match:
            ordered.append(match)
            remaining.remove(match)
    ordered.extend(step for step in method.steps if step not in ordered)
    return [step.model_copy(update={"step_number": index}) for index, step in enumerate(ordered, start=1)]


def _same_poi_name(left: str, right: str) -> bool:
    left_key = _poi_name_key(left)
    right_key = _poi_name_key(right)
    return left_key == right_key or left_key in right_key or right_key in left_key


def _poi_name_key(name: str) -> str:
    name = re.sub(r"[（(].*?[）)]", "", name)
    return re.sub(r"\s+", "", name).lower()


def _remap_content_p_numbers(content: str, source_images: list[str], target_images: list[str]) -> str:
    """把正文里基于全量候选图的 P 编号，映射到选中路线重新编号后的 P 编号。"""
    if not content or not source_images or not target_images:
        return content
    url_to_new_index = {url: index for index, url in enumerate(target_images, start=1)}

    def _replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        old_index = int(match.group(2))
        if not (1 <= old_index <= len(source_images)):
            return match.group(0)
        new_index = url_to_new_index.get(source_images[old_index - 1])
        if not new_index:
            return match.group(0)
        return f"{prefix}{new_index}"

    return _P_REF.sub(_replace, content)


def _max_p_reference(content: str) -> int:
    nums = [int(match.group(2)) for match in _P_REF.finditer(content)]
    return max(nums) if nums else 0


def _selection_system_prompt() -> str:
    return """你从一批候选玩法路线中，挑选最适合写成一篇小红书「多玩法合集」笔记的2-4条路线。
你只返回JSON：
{
  "selected_method_indexes": [2, 4, 8],
  "selected_routes": [
    {"method_index": 1, "poi_names": ["玩法一要写的第一个地点", "玩法一要写的第二个地点"]},
    {"method_index": 2, "poi_names": ["玩法二要写的地点"]}
  ]
}
说明：
- selected_method_indexes 是候选方案编号，按你决定写入正文的玩法顺序排列。
- selected_routes 的 method_index 是正文输出顺序（1=玩法一），不是候选编号。
- poi_names 必须来自对应候选方案，并按你计划写进正文的游玩顺序填写。
不要输出 markdown，不要输出 title/content/tags。"""


def _selection_user_prompt(query: str, methods_info: str, location_name: str | None) -> str:
    location_info = f"\n用户出发位置：{location_name}\n" if location_name else ""
    nearby_hint = ""
    if any(token in query for token in ("附近", "周边", "就近")):
        nearby_hint = "\n用户强调“附近”玩法：优先选择出发地周边可轻松到达的路线，不要选全市远征地标。"
    return f"""请从以下候选玩法中，挑选2-4条最适合写成一篇小红书多玩法笔记的路线。

用户查询：{query}{location_info}{nearby_hint}
候选玩法方案：
{methods_info}

要求：
1. 只返回 selected_method_indexes 和 selected_routes，不要写正文。
2. 选择的路线应覆盖不同场景或人群，避免高度重复。
3. selected_routes 里每个玩法的 poi_names 必须来自对应候选方案，顺序按游玩顺序填写。
4. 只能返回合法 JSON 对象。"""


def _content_only_system_prompt() -> str:
    return """你是一位资深的小红书旅游/城市生活类创作者，擅长做「具体人群+具体场景」的多路线玩法分享。
你的创作风格：
- 标题：有吸引力、信息具体，可以用「地点/场景｜情绪价值」或「地点攻略：几种玩法」这种结构，但不要套模板、不要单调
- 正文：像在跟朋友聊天，口语化、有情绪、有画面感
- 结构：一篇笔记里包含2-4个不同「玩法/路线/方案」，每个方案有标题、人群/场景、路线顺序和自然亮点表达
- 信息：自然带出地点名称、图片编号、大致时间、人均消费、适合什么人
- 不要在正文里暴露候选编号，例如“方案1”“方案5”“候选方案2”
- 不要出现“推荐理由”这四个字，也不要输出 restaurant、culture、tourism、shopping、other 这类英文类型词

你只返回JSON：
{
  "title": "标题（建议12-24字）",
  "content": "正文内容（800字以内）",
  "tags": ["标签1", "标签2"]
}
不要输出markdown，不要出现AI、模型、提示词等技术字眼。"""


def _selected_routes_user_prompt(query: str, methods_info: str, image_count: int, location_name: str | None) -> str:
    location_info = f"\n用户出发位置：{location_name}\n" if location_name else ""
    nearby_hint = ""
    if any(token in query for token in ("附近", "周边", "就近")):
        nearby_hint = "\n用户强调“附近”玩法：正文必须围绕出发地周边可轻松到达的地点来写，不要写成全市地标远征攻略。"
    return f"""请根据以下【已最终确定】的玩法路线，为小红书创作一篇多玩法合集笔记。

用户查询：{query}{location_info}{nearby_hint}
最终玩法方案（按正文玩法一/二/三顺序）：
{methods_info}

共有{image_count}张图片，编号为 P1 到 P{image_count}。玩法方案详情里的 [图片Px] 与上述编号一一对应。
正文提到具体地点时，必须且只能使用玩法方案详情里给出的图片编号，禁止编造 P 号，禁止跳号，禁止引用超出 P{image_count} 的编号。

要求：
1. 标题要有吸引力，建议12-24个中文字符，不要写成单调模板标题。
2. 正文必须≤800个中文字符。
3. 正文按玩法一/玩法二/玩法三依次写，每个玩法对应上面方案详情里的一条路线，POI 顺序必须与方案详情一致。
4. 正文可以自由发挥，不要写成参数表或固定模板；不要出现“方案1”“候选方案2”等内部编号。
5. 每个地点最多标两个图片编号，只使用方案详情里给出的图片编号。
6. 正文提到的所有地点必须来自方案详情，禁止编造未提供的地点。
7. 不要写“推荐理由：”，也不要写英文类型词；人群和场景用自然中文表达。
8. 输出8-12个中文标签，不要带#号。
9. 结尾鼓励用户点击左上角头像关注更多上海有趣玩法。
10. 只能返回合法JSON对象，键名必须是 title、content、tags。"""


def _system_prompt() -> str:
    return """你是一位资深的小红书旅游/城市生活类创作者，擅长做「具体人群+具体场景」的多路线玩法分享。
你的创作风格：
- 标题：有吸引力、信息具体，可以用「地点/场景｜情绪价值」或「地点攻略：几种玩法」这种结构，但不要套模板、不要单调
- 正文：像在跟朋友聊天，口语化、有情绪、有画面感
- 结构：一篇笔记里必须包含2-4个不同「玩法/路线/方案」，每个方案有标题、人群/场景、路线顺序和自然亮点表达
- 信息：自然带出地点名称、图片编号、大致时间、人均消费、适合什么人
- 不要在正文里暴露候选编号，例如“方案1”“方案5”“候选方案2”
- 不要出现“推荐理由”这四个字，也不要输出 restaurant、culture、tourism、shopping、other 这类英文类型词

你只返回JSON：
{
  "title": "标题（建议12-24字）",
  "content": "正文内容（800字以内）",
  "tags": ["标签1", "标签2"],
  "selected_method_indexes": [2, 4, 8],
  "selected_routes": [
    {"method_index": 1, "poi_names": ["正文玩法一里的第一个地点", "正文玩法一里的第二个地点"]},
    {"method_index": 2, "poi_names": ["正文玩法二里的第一个地点"]}
  ]
}
不要输出markdown，不要出现AI、模型、提示词等技术字眼。"""


def _user_prompt(query: str, methods_info: str, image_count: int, location_name: str | None) -> str:
    location_info = f"\n用户出发位置：{location_name}\n" if location_name else ""
    nearby_hint = ""
    if any(token in query for token in ("附近", "周边", "就近")):
        nearby_hint = "\n用户强调“附近”玩法：正文必须围绕出发地周边可轻松到达的地点来写，不要写成全市地标远征攻略。"
    return f"""请根据以下信息，为小红书创作一篇【城市玩法路线】笔记，重点服务一个【具体人群+具体场景】。

用户查询：{query}{location_info}{nearby_hint}
玩法方案详情：
{methods_info}

共有{image_count}张图片（P1到P{image_count}），在正文中提到具体地点时，请标注对应图片编号。

要求：
1. 标题要有吸引力，建议12-24个中文字符，不要写成“交大好友一日游”这类单调标题；可以包含地点、场景、情绪或玩法数量。
2. 正文必须≤800个中文字符。
3. 你要从候选方案里自主选择2-4个最适合写进正文的方案，顺序也由你决定；正文可以自由发挥，不要写成参数表或固定模板。
4. 必须在JSON里返回 selected_method_indexes，内容是你选择的候选方案编号，例如 [2,4,8]。正文里的玩法一/二/三必须分别对应 selected_method_indexes 的第1/2/3个编号。
5. 必须在JSON里返回 selected_routes，用来声明正文里每个玩法实际写到的 POI 顺序。selected_routes 的 method_index 是正文输出顺序（1代表正文玩法一，不是候选方案编号），poi_names 必须严格按正文里出现和游玩的顺序填写。
6. 每个玩法里的 POI 顺序必须和对应候选方案步骤顺序一致，不要自行调换。正文可以自然表达，但顺序不能乱。
7. 正文不要出现“方案1”“方案5”“候选方案2”等候选编号，只能写“路线一/玩法一”这类面向用户的编号。
8. 每个地点最多标两个图片编号，只使用玩法方案详情里给出的图片编号。
9. 正文提到的所有地点必须来自候选方案详情，禁止编造未提供的地点；没有图片编号的地点不要硬写 P 号。
10. 不要写“推荐理由：”，也不要写“适合：restaurant、culture、tourism、shopping、other”这类英文类型；人群和场景要用自然中文表达。
11. 输出8-12个中文标签，不要带#号。
12. 结尾鼓励用户点击左上角头像关注更多上海有趣玩法。
13. 只能返回合法JSON对象，键名必须是 title、content、tags、selected_method_indexes、selected_routes。"""


def _multi_system_prompt() -> str:
    return """你是一位资深的小红书城市生活创作者。你会从一批候选玩法路线中，组合生成2-4篇不同角度的小红书笔记。
你只返回JSON：
{"cards":[{"title":"15字以内标题","content":"800字以内正文","tags":["标签"]}]}
每篇要服务不同人群或场景，避免重复标题和重复路线表达。不要输出markdown，不要出现AI、模型、提示词。"""


def _multi_user_prompt(
    query: str,
    methods_info: str,
    image_count: int,
    location_name: str | None,
    min_cards: int,
    max_cards: int,
) -> str:
    location_info = f"\n用户当前位置/出发地：{location_name}\n" if location_name else ""
    return f"""请基于候选玩法，为同一个用户需求生成{min_cards}-{max_cards}篇不同角度的小红书玩法笔记。

用户查询：{query}{location_info}
候选玩法方案：
{methods_info}

共有{image_count}张图片（P1到P{image_count}），正文提到具体地点时请标注图片编号。

要求：
1. 每篇标题≤15个中文字符。
2. 每篇正文≤800个中文字符。
3. 每篇选2-4条最合适玩法路线，不要硬塞全部候选。
4. 每篇8-12个中文标签，不带#号。
5. 结尾鼓励用户点击左上角头像关注更多上海有趣玩法。
6. 只返回合法JSON对象，顶层键名必须是 cards。"""


def _fallback_content(query: str, methods: list[PlayMethod]) -> str:
    titles = "、".join(method.title for method in methods[:3])
    return f"这次围绕「{query}」整理了{titles or '几条上海玩法'}，适合想轻松出门又不想踩雷的时候参考。觉得有用的话，点左上角头像关注更多上海有趣玩法。"

