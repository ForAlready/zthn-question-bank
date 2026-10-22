"""全局配额分配：交叉标签不产生假不足。"""
import random

from app.services.paper_engine.assign import assign_quota_slots, bipartite_match


def test_overlapping_tags_assigned_once_feasible():
    """Q1 同时命中 A/B；贪心先抽 A 会假不足，全局匹配应成功。"""
    # pools by id
    pool_a = [1, 2]  # Q1(A+B), Q2(A)
    pool_b = [1]  # only Q1
    rng = random.Random(0)
    # 多次尝试：匹配应总能找到 Q2->A, Q1->B
    success = 0
    for salt in range(20):
        assigned = assign_quota_slots(
            [pool_a, pool_b], [1, 1], rng=random.Random(salt)
        )
        if assigned is None:
            continue
        success += 1
        flat = assigned[0] + assigned[1]
        assert len(flat) == len(set(flat))
        assert set(flat) == {1, 2}
        assert assigned[0] == [2]
        assert assigned[1] == [1]
    assert success >= 1


def test_overlapping_truly_insufficient():
    """仅一题带双标签，两配额各需 1 → 真不足。"""
    assigned = assign_quota_slots([[1], [1]], [1, 1], rng=random.Random(1))
    assert assigned is None


def test_bipartite_match_full():
    slots = [[10, 20], [20, 30], [10]]
    matched = bipartite_match(slots, rng=random.Random(2))
    assert None not in matched
    assert len(set(matched)) == 3
