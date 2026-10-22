"""合并已观察到的模型响应用量，明确区分完整总量和已知下界。"""

from collections.abc import Iterable, Mapping


def aggregate_usage(
    responses: Iterable[Mapping[str, int | float] | None],
) -> dict[str, int | float] | None:
    """字段只有在所有响应均已知时才叫总量，缺失字段保留 known_ 下界。"""

    items = list(responses)
    fields = {name for item in items if item is not None for name in item}
    if not fields:
        return None
    result: dict[str, int | float] = {}
    for name in fields:
        # 只对实际存在的数值求和；缺失响应不贡献一个虚构的零。
        values = [item[name] for item in items if item is not None and name in item]
        key = name if len(values) == len(items) else f"known_{name}"
        result[key] = sum(values)
    missing = sum(item is None for item in items)
    if missing:
        result["responses_without_usage"] = missing
    return result
