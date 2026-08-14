import time

from collections.abc import Callable

from app.agent_models import AgentState, DiscoveryRequest, DiscoveryResponse, PlayMethod
from app.agents import ExecuteAgent, PlannerAgent
from app.amap_tool import AmapTool
from app.deepseek_client import DeepSeekClient


LogCallback = Callable[[str, str], None] | None


class PlayDiscoveryWorkflow:
    def __init__(
        self,
        amap_tool: AmapTool,
        deepseek_client: DeepSeekClient | None = None,
        max_rounds: int = 3,
        log_callback: LogCallback = None,
    ):
        deepseek = deepseek_client or DeepSeekClient()
        self.planner = PlannerAgent(deepseek)
        self.execute_agent = ExecuteAgent(amap_tool, deepseek)
        self.max_rounds = max_rounds
        self.log_callback = log_callback
        self._logged_debug_count = 0

    def _emit(self, stage: str, message: str) -> None:
        if self.log_callback:
            self.log_callback(stage, message)

    def _flush_debug_logs(self, state: AgentState) -> None:
        new_logs = state.debug_logs[self._logged_debug_count :]
        for line in new_logs:
            self._emit("agent", line)
        self._logged_debug_count = len(state.debug_logs)

    async def run(self, request: DiscoveryRequest, log_callback: LogCallback = None) -> DiscoveryResponse:
        if log_callback:
            self.log_callback = log_callback
        self._logged_debug_count = 0
        started_at = time.time()
        state = AgentState(
            user_query=request.query,
            user_location=request.user_location,
            user_location_name=request.preferences.get("location_text"),
            preferences=request.preferences,
            max_depth=request.max_depth,
            max_paths=request.max_results,
        )
        try:
            self._emit("workflow", "开始 Plan + Execute 玩法发现")
            state.add_debug_log("workflow:start")
            state = await self.planner.plan_initial(state)
            self._flush_debug_logs(state)
            self._emit("planner", f"Planner 已规划 {len(state.active_node_ids)} 条初始玩法方向")
            for round_index in range(self.max_rounds):
                state.iteration_count = round_index + 1
                state.add_debug_log(f"workflow:round:{round_index + 1}:execute")
                if not state.active_node_ids:
                    break
                self._emit("workflow", f"第 {round_index + 1} 轮：Execute Agent 正在搜索并筛选 POI")
                state = await self.execute_agent.execute(state)
                self._flush_debug_logs(state)
                expandable = [
                    node_id
                    for node_id, node in state.path_nodes.items()
                    if node.status.value == "completed" and node.path_history and node.depth + 1 < state.max_depth
                ]
                if round_index + 1 >= self.max_rounds or not expandable:
                    break
                state.add_debug_log(f"workflow:round:{round_index + 1}:recursive_planning:{len(expandable)}")
                self._emit("planner", f"第 {round_index + 1} 轮：Planner 正在补充下一跳玩法")
                state = await self.planner.plan_recursive(state, expandable)
                self._flush_debug_logs(state)
            _finalize_completed_nodes(state)
            play_methods = _build_play_methods(state)
            self._emit("workflow", f"玩法发现完成，共生成 {len(play_methods)} 条候选路线")
            return DiscoveryResponse(
                success=True,
                message="玩法发现完成",
                play_methods=play_methods,
                total_count=len(play_methods),
                processing_time=time.time() - started_at,
                debug_info={"debug_logs": state.debug_logs},
            )
        except Exception as exc:
            detail = str(exc).strip() or f"{type(exc).__name__}"
            return DiscoveryResponse(
                success=False,
                message=f"玩法发现失败: {detail}",
                play_methods=[],
                total_count=0,
                processing_time=time.time() - started_at,
                debug_info={"error": detail, "error_type": type(exc).__name__, "debug_logs": state.debug_logs},
            )


def _build_play_methods(state: AgentState) -> list[PlayMethod]:
    methods: list[PlayMethod] = []
    for index, path in enumerate(state.completed_paths, start=1):
        if not path:
            continue
        total_duration = sum(step.duration_minutes for step in path)
        first_plan_title = path[0].description.replace("执行计划：", "")
        methods.append(
            PlayMethod(
                title=first_plan_title or f"玩法路线{index}",
                description=f"包含{len(path)}个地点的完整体验路线",
                steps=path,
                total_duration_minutes=max(total_duration, 1),
                difficulty_level=1 if len(path) <= 1 else 2,
                tags=_method_tags(path),
                rating=_average_rating(path),
            )
        )
    return methods


def _finalize_completed_nodes(state: AgentState) -> None:
    parent_ids = {node.parent_id for node in state.path_nodes.values() if node.parent_id}
    for node_id, node in list(state.path_nodes.items()):
        if node.status.value != "completed":
            continue
        if node_id in parent_ids:
            continue
        state.complete_path(node_id)


def _method_tags(path) -> list[str]:
    tags = []
    for step in path:
        if step.poi.category.value not in tags:
            tags.append(step.poi.category.value)
    if len(path) == 1:
        tags.append("短途")
    return tags


def _average_rating(path) -> float:
    ratings = [step.poi.rating for step in path if step.poi.rating]
    if not ratings:
        return 0.0
    return round(sum(ratings) / len(ratings), 2)

