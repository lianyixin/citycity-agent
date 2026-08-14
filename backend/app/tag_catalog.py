TAG_CANONICAL_ALIASES: dict[str, str] = {
    "城市散步": "城市漫步",
    "城市漫游": "城市漫步",
    "周末去哪儿": "周末去哪",
    "周末去哪玩": "周末去哪",
    "上海周末去哪玩": "周末去哪",
    "上海周末去哪儿": "周末去哪",
    "上海周末去哪": "周末去哪",
    "下班去哪里": "下班去哪",
    "下班去哪儿": "下班去哪",
    "下班去哪玩": "下班去哪",
    "下班后去哪": "下班去哪",
    "上班族下班去哪": "下班去哪",
    "上海下班去哪": "下班去哪",
}


def canonicalize_tag(tag: str) -> str:
    normalized = str(tag).strip()
    if not normalized:
        return normalized
    return TAG_CANONICAL_ALIASES.get(normalized, normalized)
