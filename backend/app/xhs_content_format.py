import re

_NUM = r"[一二三四五六七八九十百千万\dA-Za-z]+"
_EMOJI_PREFIX = r"(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]\s*){0,3}"

_SECTION_BRACKET_RE = re.compile(
    rf"^.{{0,12}}?【[^】]*(?:玩法|路线|方案){_NUM}[^】]*】"
)
_SECTION_COLON_RE = re.compile(
    rf"^.{{0,24}}?(?:玩法|路线){_NUM}[：:]"
)
_PLAN_COLON_RE = re.compile(
    rf"^{_EMOJI_PREFIX}方案{_NUM}[：:]"
)
_SUMMARY_MARKERS = ("觉得有用", "各有侧重", "点我头像", "点左上角", "总有一款", "总有一条")


def is_section_title_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False
    if stripped.startswith("**") and stripped.endswith("**"):
        return False
    if stripped.startswith("总结"):
        return False
    if any(marker in stripped for marker in _SUMMARY_MARKERS):
        return False
    detection = re.sub(r"\*\*", "", stripped)
    return bool(
        _SECTION_BRACKET_RE.search(detection)
        or _SECTION_COLON_RE.search(detection)
        or _PLAN_COLON_RE.search(detection)
    )


def bold_section_title_line(line: str) -> str:
    stripped = line.strip()
    if not is_section_title_line(stripped):
        return line
    inner = re.sub(r"\*\*", "", stripped)
    return f"**{inner}**"


def format_xhs_content(content: str) -> str:
    if not content:
        return content
    return "\n".join(bold_section_title_line(line) for line in content.split("\n"))
