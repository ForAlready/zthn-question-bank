"""全局可行分配：配额交叉标签用二分图匹配（Kuhn），避免顺序贪心假不足。"""
from __future__ import annotations

import random
from typing import Hashable, Iterable, Optional, Sequence, TypeVar

T = TypeVar("T", bound=Hashable)


def bipartite_match(
    slot_candidates: Sequence[Sequence[T]],
    *,
    rng: Optional[random.Random] = None,
) -> list[Optional[T]]:
    """对每个 slot 从其候选中分配互不重复的元素。

    返回与 slot 等长的分配列表；若无法满配则对应位置为 None（整体不完全）。
    通过打乱候选顺序引入随机性。
    """
    n = len(slot_candidates)
    if n == 0:
        return []

    # 归一化并可选打乱
    prepared: list[list[T]] = []
    for cands in slot_candidates:
        items = list(dict.fromkeys(cands))  # 保序去重
        if rng is not None:
            rng.shuffle(items)
        prepared.append(items)

    # item -> assigned slot index
    matched_to: dict[T, int] = {}

    def dfs(slot: int, seen: set[T]) -> bool:
        for item in prepared[slot]:
            if item in seen:
                continue
            seen.add(item)
            owner = matched_to.get(item)
            # 候选已被占用时，先为原题位寻找替代项；允许重排已有分配以满足交叉配额。
            if owner is None or dfs(owner, seen):
                matched_to[item] = slot
                return True
        return False

    order = list(range(n))
    if rng is not None:
        rng.shuffle(order)

    for slot in order:
        dfs(slot, set())

    assignment: list[Optional[T]] = [None] * n
    for item, slot in matched_to.items():
        assignment[slot] = item
    return assignment


def assign_quota_slots(
    quota_pools: Sequence[Sequence[T]],
    quota_counts: Sequence[int],
    *,
    rng: Optional[random.Random] = None,
) -> Optional[list[list[T]]]:
    """按配额池做全局分配。

    quota_pools[i] 为第 i 个配额的候选；quota_counts[i] 为需求题量。
    成功返回与配额等长的已选题列表；失败返回 None。
    """
    if len(quota_pools) != len(quota_counts):
        raise ValueError("quota_pools 与 quota_counts 长度不一致")

    slots: list[list[T]] = []
    slot_quota_index: list[int] = []
    for qi, (pool, count) in enumerate(zip(quota_pools, quota_counts)):
        if count < 0:
            raise ValueError("quota count 不能为负")
        # 每个配额名额展开成独立题位，共用匹配表确保一题最多占用一个名额。
        for _ in range(count):
            slots.append(list(pool))
            slot_quota_index.append(qi)

    if not slots:
        return [[] for _ in quota_counts]

    matched = bipartite_match(slots, rng=rng)
    if any(m is None for m in matched):
        return None

    result: list[list[T]] = [[] for _ in quota_counts]
    for slot_i, item in enumerate(matched):
        if item is None:
            return None
        result[slot_quota_index[slot_i]].append(item)
    return result


def max_matching_size(slot_candidates: Iterable[Sequence[T]]) -> int:
    """返回可成功分配的 slot 数量（诊断用）。"""
    matched = bipartite_match(list(slot_candidates))
    return sum(1 for m in matched if m is not None)
