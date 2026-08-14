import asyncio
import json
import os
import re

from app.agent_models import (
    AgentState,
    PathNode,
    PathNodeStatus,
    PlayPlan,
    PlayStep,
    POICategory,
)
from app.geo_utils import distance_from_user_meters
from app.amap_tool import AmapTool
from app.deepseek_client import DeepSeekClient


def default_city() -> str:
    return os.getenv("DEFAULT_CITY", "上海").strip() or "上海"


class PlannerAgent:
    def __init__(self, deepseek_client: DeepSeekClient | None = None):
        self.deepseek = deepseek_client or DeepSeekClient()

    async def plan_initial(self, state: AgentState) -> AgentState:
        try:
            plans = await self._llm_plan(state, mode="initial")
        except Exception as exc:
            state.add_debug_log(f"PlannerAgent LLM initial failed: {exc}")
            plans = _fallback_initial_plans(state)
        return _append_root_plans(state, plans)

    async def plan_recursive(self, state: AgentState, node_ids: list[str]) -> AgentState:
        for node_id in node_ids:
            node = state.get_node(node_id)
            if not node or not node.path_history or node.depth + 1 >= state.max_depth:
                continue
            try:
                plans = await self._llm_plan(state, mode="recursive", node=node)
            except Exception as exc:
                state.add_debug_log(f"PlannerAgent LLM recursive failed: {exc}")
                fallback = _next_plan_for_path(state, node)
                plans = [fallback] if fallback else []
            for next_plan in plans[:2]:
                child = PathNode(
                    parent_id=node_id,
                    depth=node.depth + 1,
                    status=PathNodeStatus.RUNNING,
                    path_history=node.path_history.copy(),
                )
                child.start_path_timing()
                child.pending_plans.append(next_plan)
                child_id = state.add_node(child)
                node.add_child(child_id)
                state.active_node_ids.append(child_id)
                state.add_debug_log(f"PlannerAgent expanded from {node.path_history[-1].poi.name} to {next_plan.title}")
        return state

    async def _llm_plan(self, state: AgentState, mode: str, node: PathNode | None = None) -> list[PlayPlan]:
        prompt = _planner_prompt(state, mode, node)
        response = await self.deepseek.chat_completion(
            prompt=prompt,
            system_message=_planner_system_prompt(),
            temperature=0.85,
            max_tokens=1800,
        )
        data = _parse_json(response)
        raw_plans = data.get("plans") if isinstance(data, dict) else []
        if not isinstance(raw_plans, list):
            return []
        plans: list[PlayPlan] = []
        for item in raw_plans:
            if not isinstance(item, dict):
                continue
            keywords = item.get("keywords")
            if not isinstance(keywords, list):
                keywords = [item.get("title", "")]
            category = _parse_category(item.get("category"))
            plans.append(
                PlayPlan(
                    title=str(item.get("title") or "玩法计划")[:80],
                    description=str(item.get("description") or ""),
                    keywords=[str(keyword).strip() for keyword in keywords if str(keyword).strip()][:5],
                    category=category,
                    priority=float(item.get("priority") or 0.7),
                    suitable_start_time=str(item.get("suitable_start_time") or state.preferences.get("time_context") or ""),
                    duration_minutes=_parse_int(item.get("duration_minutes")),
                    context={"reasoning": data.get("reasoning")},
                )
            )
        return plans[: max(state.max_paths, 1)]


class TemplatePlannerAgent:
    def plan_initial(self, state: AgentState) -> AgentState:
        preferences = state.preferences
        location_text = preferences.get("location_text") or _extract_location_hint(state.user_query) or default_city()
        time_context = preferences.get("time_context") or _extract_time_hint(state.user_query)
        tags = preferences.get("preference_tags") or []

        plan_specs = [
            ("拍照打卡路线", ["拍照", "地标", location_text], POICategory.CULTURE),
            ("美食休息路线", ["美食", "咖啡", location_text], POICategory.RESTAURANT),
            ("城市散步路线", ["citywalk", "公园", location_text], POICategory.TOURISM),
        ]
        if tags:
            plan_specs.insert(0, (f"{tags[0]}主题路线", [tags[0], location_text], _category_from_tag(tags[0])))

        for title, keywords, category in plan_specs[: state.max_paths]:
            node = PathNode(status=PathNodeStatus.RUNNING)
            node.start_path_timing()
            node.pending_plans.append(
                PlayPlan(
                    title=f"{location_text}{title}",
                    description=f"围绕{location_text}和{time_context}生成的玩法思路",
                    keywords=[keyword for keyword in keywords if keyword],
                    category=category,
                    priority=0.8,
                    suitable_start_time=time_context,
                )
            )
            node_id = state.add_node(node)
            state.active_node_ids.append(node_id)
        state.add_debug_log(f"PlannerAgent created {len(state.active_node_ids)} root plans")
        return state

    def plan_recursive(self, state: AgentState, node_ids: list[str]) -> AgentState:
        for node_id in node_ids:
            node = state.get_node(node_id)
            if not node or not node.path_history or node.depth + 1 >= state.max_depth:
                continue
            last_step = node.path_history[-1]
            next_plan = _next_plan_for_path(state, node)
            if not next_plan:
                continue
            child = PathNode(
                parent_id=node_id,
                depth=node.depth + 1,
                status=PathNodeStatus.RUNNING,
                path_history=node.path_history.copy(),
            )
            child.start_path_timing()
            child.pending_plans.append(next_plan)
            child_id = state.add_node(child)
            node.add_child(child_id)
            state.active_node_ids.append(child_id)
            state.add_debug_log(f"PlannerAgent expanded from {last_step.poi.name} to child plan {next_plan.title}")
        return state


class ExecuteAgent:
    def __init__(
        self,
        amap_tool: AmapTool,
        deepseek_client: DeepSeekClient | None = None,
        max_parallel_routes: int | None = None,
    ):
        self.amap_tool = amap_tool
        self.deepseek = deepseek_client or DeepSeekClient()
        configured = max_parallel_routes or int(os.getenv("MAX_PARALLEL_ROUTES", "4"))
        self.max_parallel_routes = max(1, configured)

    async def execute(self, state: AgentState) -> AgentState:
        node_ids = [
            node_id
            for node_id in list(state.active_node_ids)
            if (node := state.get_node(node_id)) is not None and node.pending_plans
        ]
        semaphore = asyncio.Semaphore(self.max_parallel_routes)

        async def execute_bounded(node_id: str) -> bool:
            async with semaphore:
                return await self._execute_node(state, node_id)

        results = await asyncio.gather(
            *(execute_bounded(node_id) for node_id in node_ids),
            return_exceptions=True,
        )
        completed_node_ids: list[str] = []
        errors: list[Exception] = []
        for node_id, result in zip(node_ids, results):
            if isinstance(result, Exception):
                errors.append(result)
                state.add_debug_log(f"ExecuteAgent branch failed: {node_id}: {type(result).__name__}: {result}")
            elif result:
                completed_node_ids.append(node_id)

        if errors and len(errors) == len(node_ids):
            raise errors[0]
        for node_id in completed_node_ids:
            if node_id in state.active_node_ids:
                state.active_node_ids.remove(node_id)
        state.add_debug_log(
            f"ExecuteAgent completed {len(completed_node_ids)} paths "
            f"with concurrency={self.max_parallel_routes}"
        )
        return state

    async def _execute_node(self, state: AgentState, node_id: str) -> bool:
        location = _location_string(state.user_location)
        node = state.get_node(node_id)
        if not node or not node.pending_plans:
            return False
        plan = node.pending_plans.pop(0)
        node.current_plan = plan
        search_query = _build_search_query(plan)
        search_location = location
        if node.path_history:
            last_step = node.path_history[-1]
            if last_step.poi.longitude and last_step.poi.latitude:
                search_location = f"{last_step.poi.longitude},{last_step.poi.latitude}"
        state.add_debug_log(
            f"ExecuteAgent searching: {search_query}, location={search_location or 'city'}, radius=5000"
        )
        pois = await self.amap_tool.search_pois(
            query=search_query,
            location=search_location,
            city=_city_for_state(state),
            radius=5000,
            limit=12,
        )
        _annotate_poi_distances(pois, state.user_location)
        if not pois:
            node.status = PathNodeStatus.NO_SUITABLE_POI
            state.add_debug_log(f"ExecuteAgent no POI for {plan.title}")
            return True
        poi, reason, duration = await self._select_poi(state, plan, pois)
        if poi is None:
            node.status = PathNodeStatus.NO_SUITABLE_POI
            state.add_debug_log(f"ExecuteAgent no suitable POI for {plan.title}")
            return True
        step = PlayStep(
            step_number=len(node.path_history) + 1,
            poi=poi,
            estimated_start_time=plan.suitable_start_time,
            duration_minutes=duration or plan.duration_minutes or _duration_for_category(plan.category),
            description=f"执行计划：{plan.title}",
            recommendation_reason=reason or f"根据关键词 {search_query} 选择评分和信息较完整的地点。",
        )
        node.add_step(step)
        node.status = PathNodeStatus.COMPLETED
        state.add_debug_log(f"ExecuteAgent selected {poi.name} for {plan.title}")
        return True

    async def _select_poi(
        self,
        state: AgentState,
        plan: PlayPlan,
        pois: list,
    ):
        try:
            response = await self.deepseek.chat_completion(
                prompt=_execute_prompt(state, plan, pois),
                system_message=_execute_system_prompt(),
                temperature=0.35,
                max_tokens=1200,
            )
            data = _parse_json(response)
            if data.get("no_suitable_poi") is True:
                return None, str(data.get("reasoning") or ""), None
            selected_id = str(data.get("selected_poi_id") or "")
            selected_name = str(data.get("selected_poi_name") or "")
            for poi in pois:
                if selected_id and poi.amap_poi_id == selected_id:
                    return poi, str(data.get("reasoning") or ""), _parse_int(data.get("estimated_duration"))
                if selected_name and poi.name == selected_name:
                    return poi, str(data.get("reasoning") or ""), _parse_int(data.get("estimated_duration"))
        except Exception as exc:
            state.add_debug_log(f"ExecuteAgent LLM select failed: {exc}")
        return _best_poi_by_rating(pois), "", None


def _build_search_query(plan: PlayPlan) -> str:
    return " ".join(plan.keywords[:3]) or plan.title


def _location_string(user_location: dict[str, float] | None) -> str | None:
    if not user_location:
        return None
    lng = user_location.get("lng")
    lat = user_location.get("lat")
    if lng is None or lat is None:
        return None
    return f"{lng},{lat}"


def _city_for_state(state: AgentState) -> str:
    return str(
        state.preferences.get("target_area")
        or state.preferences.get("location_text")
        or state.user_location_name
        or default_city()
    )


def _duration_for_category(category: POICategory) -> int:
    if category == POICategory.RESTAURANT:
        return 90
    if category in {POICategory.TOURISM, POICategory.CULTURE}:
        return 75
    return 60


def _extract_location_hint(query: str) -> str | None:
    for marker in ["附近", "周边"]:
        if marker in query:
            before = query.split(marker)[0]
            return before[-8:].strip() or None
    return None


def _append_root_plans(state: AgentState, plans: list[PlayPlan]) -> AgentState:
    for plan in plans[: state.max_paths]:
        node = PathNode(status=PathNodeStatus.RUNNING)
        node.start_path_timing()
        node.pending_plans.append(plan)
        node_id = state.add_node(node)
        state.active_node_ids.append(node_id)
    state.add_debug_log(f"PlannerAgent created {len(plans[: state.max_paths])} root plans")
    return state


def _fallback_initial_plans(state: AgentState) -> list[PlayPlan]:
    temp = AgentState(
        user_query=state.user_query,
        user_location=state.user_location,
        user_location_name=state.user_location_name,
        preferences=state.preferences,
        max_depth=state.max_depth,
        max_paths=state.max_paths,
    )
    TemplatePlannerAgent().plan_initial(temp)
    plans: list[PlayPlan] = []
    for node_id in temp.active_node_ids:
        node = temp.get_node(node_id)
        if node:
            plans.extend(node.pending_plans)
    return plans


def _annotate_poi_distances(pois: list, user_location: dict[str, float] | None) -> None:
    if not user_location:
        return
    for poi in pois:
        distance = distance_from_user_meters(user_location, poi.latitude, poi.longitude)
        if distance is not None:
            poi.distance_meters = distance


def _planner_system_prompt() -> str:
    return """你是城市玩法规划师。你只负责规划玩法方向，不选择具体POI。
必须输出JSON：{"reasoning":"...","plans":[{"title":"...","description":"...","keywords":["..."],"category":"restaurant|entertainment|shopping|tourism|sports|culture|nightlife|outdoor|wellness|other","priority":0.8,"suitable_start_time":"...","duration_minutes":90}]}。
初始规划给3-6个多样玩法；递归规划给0-2个下一步玩法。尊重用户地点、同行人、时间和偏好，关键词必须可用于地图 POI 搜索。
如果用户指定了目标游玩区域，玩法方向和搜索关键词必须围绕目标游玩区域；出发位置只用于理解交通出发点，不能替代目标游玩区域。
如果用户需求强调“附近/周边/就近”，所有玩法必须围绕出发地3-5公里内，不要规划跨区地标远征（如迪士尼、外滩、南京路），关键词也要本地化。"""


def _planner_prompt(state: AgentState, mode: str, node: PathNode | None) -> str:
    location = state.preferences.get("location_text") or state.user_location_name or default_city()
    target_area = state.preferences.get("target_area") or "未指定"
    nearby_intent = bool(state.preferences.get("nearby_intent"))
    nearby_rule = ""
    if nearby_intent:
        nearby_rule = (
            "\n【附近约束】用户明确想找“附近”玩法。所有计划必须围绕出发地3-5公里内，"
            "优先夜市、商圈、公园、酒吧、餐厅、亲子乐园等本地可达地点；"
            "禁止把迪士尼、外滩、南京路、陆家嘴观景等跨区地标作为核心玩法。"
        )
    history = ""
    if node and node.path_history:
        history = "\n已选路径：" + " -> ".join(step.poi.name for step in node.path_history)
    return f"""模式：{mode}
用户需求：{state.user_query}
目标游玩区域：{target_area}
出发位置：{location}
坐标：{state.user_location or "无"}
时间：{state.preferences.get("time_context") or "未指定"}
同行：{state.preferences.get("companion_type") or "未指定"}
偏好：{state.preferences.get("preference_tags") or []}{nearby_rule}{history}
请输出JSON。"""


def _execute_system_prompt() -> str:
    return """你是POI筛选专家。根据玩法计划和地图候选 POI，选择最符合玩法、距离和体验的一项。
只输出JSON：{"selected_poi_id":"地图POI id","selected_poi_name":"名称","estimated_duration":90,"reasoning":"一句话推荐理由"}。
如果都明显不适合，输出{"no_suitable_poi":true,"reasoning":"原因"}。"""


def _execute_prompt(state: AgentState, plan: PlayPlan, pois: list) -> str:
    nearby_intent = bool(state.preferences.get("nearby_intent"))
    candidates = []
    for poi in pois[:12]:
        candidates.append(
            {
                "id": poi.amap_poi_id,
                "name": poi.name,
                "address": poi.address,
                "category": poi.category.value,
                "rating": poi.rating,
                "business_area": poi.business_area,
                "type_code": poi.type_code,
                "distance_meters": poi.distance_meters,
            }
        )
    nearby_rule = ""
    if nearby_intent:
        nearby_rule = "\n附近模式：优先选择距离用户出发地更近、步行/短途可达的POI，不要选明显跨区远征的地标。"
    return f"""用户需求：{state.user_query}
玩法计划：{plan.model_dump()}
候选POI：{json.dumps(candidates, ensure_ascii=False)}{nearby_rule}
请选择最合适的一项并输出JSON。"""


def _parse_json(response: str) -> dict:
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        return {}
    return json.loads(match.group())


def _parse_category(raw) -> POICategory:
    try:
        return POICategory(str(raw))
    except ValueError:
        return POICategory.OTHER


def _parse_int(raw) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _best_poi_by_rating(pois):
    return sorted(pois, key=lambda poi: (poi.rating or 0.0, bool(poi.photos)), reverse=True)[0]


def _extract_time_hint(query: str) -> str:
    for hint in ["周末晚上", "周末", "今晚", "晚上", "下午", "下班"]:
        if hint in query:
            return hint
    return "最近"


def _category_from_tag(tag: str) -> POICategory:
    if "美食" in tag:
        return POICategory.RESTAURANT
    if "拍照" in tag:
        return POICategory.CULTURE
    if "Citywalk" in tag or "citywalk" in tag:
        return POICategory.TOURISM
    return POICategory.OTHER


def _next_plan_for_path(state: AgentState, node: PathNode) -> PlayPlan | None:
    preferences = state.preferences
    tags = preferences.get("preference_tags") or []
    used_categories = {step.poi.category for step in node.path_history}
    location_text = preferences.get("location_text") or default_city()
    if POICategory.RESTAURANT not in used_categories and any("美食" in tag for tag in tags):
        return PlayPlan(
            title=f"{location_text}美食收尾",
            description="上一站之后安排吃饭或咖啡休息",
            keywords=["美食", "餐厅", location_text],
            category=POICategory.RESTAURANT,
            priority=0.75,
            suitable_start_time=preferences.get("time_context"),
        )
    if POICategory.CULTURE not in used_categories and any("拍照" in tag for tag in tags):
        return PlayPlan(
            title=f"{location_text}拍照补充",
            description="补充一个适合拍照的文化或地标点",
            keywords=["拍照", "地标", location_text],
            category=POICategory.CULTURE,
            priority=0.7,
            suitable_start_time=preferences.get("time_context"),
        )
    if len(node.path_history) < 2:
        return PlayPlan(
            title=f"{location_text}散步收尾",
            description="用轻松散步作为路线收尾",
            keywords=["散步", "公园", location_text],
            category=POICategory.TOURISM,
            priority=0.6,
            suitable_start_time=preferences.get("time_context"),
        )
    return None

