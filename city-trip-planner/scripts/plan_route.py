#!/usr/bin/env python3
"""plan_route.py — 城市出行路线装配与 ABC 三档方案生成（确定性计算）

职责：
  - 解析同行人年龄结构，按"最弱成员 × 0.85"求组合强度上限
  - 计算点位间球面距离与位移耗时
  - 按锚点 / 半径聚类，切分半场
  - 簇内开放路径 TSP（n<=10 精确解，n>10 启发式）
  - 时间窗装配、硬约束校验、ABC 三档方案对比

边界：
  - 本脚本不包含任何真实 POI 数据，也不访问网络。
  - 输入 JSON 中的点位必须由真实数据源（地图 API / Web 检索 / 用户提供）获得。
  - 年龄阈值与分档参数为经验默认值，允许用户覆盖。
  - 脚本只负责确定性计算；点位取舍与叙事由 Agent 完成。

用法：
  python plan_route.py --input itinerary.json --output route.json
  python plan_route.py --input itinerary.json --plans 1
"""

import argparse
import json
import math
import sys
from datetime import date

PARTY_PROFILES = {
    "general": {"walk_factor": 1.0, "buffer_ratio": 0.15},
    "solo": {"walk_factor": 1.0, "buffer_ratio": 0.15},
    "couple": {"walk_factor": 1.0, "buffer_ratio": 0.15},
    "friends": {"walk_factor": 1.1, "buffer_ratio": 0.15},
    "family_with_kids": {"walk_factor": 0.7, "buffer_ratio": 0.25},
    "elderly": {"walk_factor": 0.6, "buffer_ratio": 0.25},
}

PARTY_BAND_MAP = {
    "general": "36-50",
    "solo": "18-25",
    "couple": "18-25",
    "friends": "18-25",
    "family_with_kids": "4-6",
    "elderly": "70+",
}

AGE_PROFILES = {
    "0-3": {
        "label": "婴幼儿（依赖期）",
        "walk_factor": 0.25,
        "buffer_ratio": 0.35,
        "queue_tolerance_min": 10,
        "hard_constraints": ["stroller", "nursery", "no_steps", "nap_rigid", "needs_indoor"],
        "decision_weight": 0.35,
    },
    "4-6": {
        "label": "学龄前（体验期）",
        "walk_factor": 0.50,
        "buffer_ratio": 0.30,
        "queue_tolerance_min": 15,
        "hard_constraints": ["stroller_optional", "needs_indoor"],
        "decision_weight": 0.30,
    },
    "7-12": {
        "label": "小学（成长期）",
        "walk_factor": 1.08,
        "buffer_ratio": 0.25,
        "queue_tolerance_min": 30,
        "hard_constraints": [],
        "decision_weight": 0.25,
    },
    "13-17": {
        "label": "青少年（独立期）",
        "walk_factor": 1.67,
        "buffer_ratio": 0.15,
        "queue_tolerance_min": 45,
        "hard_constraints": [],
        "decision_weight": 0.20,
    },
    "18-25": {
        "label": "青年（探索期）",
        "walk_factor": 2.08,
        "buffer_ratio": 0.15,
        "queue_tolerance_min": 60,
        "hard_constraints": [],
        "decision_weight": 0.10,
    },
    "26-35": {
        "label": "青年家庭（双轨期）",
        "walk_factor": 1.67,
        "buffer_ratio": 0.20,
        "queue_tolerance_min": 45,
        "hard_constraints": [],
        "decision_weight": 0.15,
    },
    "36-50": {
        "label": "中年（承载期）",
        "walk_factor": 1.33,
        "buffer_ratio": 0.20,
        "queue_tolerance_min": 30,
        "hard_constraints": [],
        "decision_weight": 0.10,
    },
    "51-60": {
        "label": "中老年（活跃期）",
        "walk_factor": 1.08,
        "buffer_ratio": 0.20,
        "queue_tolerance_min": 20,
        "hard_constraints": [],
        "decision_weight": 0.15,
    },
    "61-70": {
        "label": "老年（舒适期）",
        "walk_factor": 0.67,
        "buffer_ratio": 0.25,
        "queue_tolerance_min": 15,
        "hard_constraints": ["avoid_stairs", "rest_frequent"],
        "decision_weight": 0.30,
    },
    "70+": {
        "label": "高龄（照护期）",
        "walk_factor": 0.40,
        "buffer_ratio": 0.35,
        "queue_tolerance_min": 10,
        "hard_constraints": ["avoid_stairs", "needs_indoor", "medical_near"],
        "decision_weight": 0.40,
    },
}

BAND_ALIASES = {
    "A1": "0-3",
    "A2": "4-6",
    "A3": "7-12",
    "A4": "13-17",
    "A5": "18-25",
    "A6": "26-35",
    "A7": "36-50",
    "A8": "51-60",
    "A9": "61-70",
    "A10": "70+",
}

TRIP_TYPE_PROFILES = {
    "local_halfday": {"b_max_pois": 3, "a_max_pois": 5, "c_max_pois": 2, "buffer_delta": 0.00},
    "local_fullday": {"b_max_pois": 4, "a_max_pois": 6, "c_max_pois": 3, "buffer_delta": 0.00},
    "day_trip": {"b_max_pois": 4, "a_max_pois": 6, "c_max_pois": 3, "buffer_delta": 0.05},
    "multiday": {"b_max_pois": 3, "a_max_pois": 5, "c_max_pois": 2, "buffer_delta": 0.05},
}

EXPERIENCE_FACTORS = {
    "novice": 0.85,
    "experienced": 0.92,
}

MULTIGENERATIONAL_PROFILE = {
    "a_max_pois": 4,
    "b_max_pois": 3,
    "c_max_pois": 2,
    "buffer_floor": 0.30,
    "rest_protected_min": 90,
    "a_walk_cap": 1.10,
}

VARIANTS = {
    "A": {
        "name": "尽兴版",
        "slogan": "体验最优，强度最高",
        "priority": 1,
        "walk_multiplier": 1.30,
        "buffer_delta": -0.05,
        "taxi_threshold_multiplier": 1.5,
        "max_pois_key": "a_max_pois",
        "filter": "all",
    },
    "B": {
        "name": "舒适版",
        "slogan": "均衡省力，默认推荐",
        "priority": 2,
        "walk_multiplier": 1.00,
        "buffer_delta": 0.00,
        "taxi_threshold_multiplier": 1.0,
        "max_pois_key": "b_max_pois",
        "filter": "no_optional",
    },
    "C": {
        "name": "省心版",
        "slogan": "低预算低风险，雨天与体力不足时优选",
        "priority": 3,
        "walk_multiplier": 0.75,
        "buffer_delta": 0.10,
        "taxi_threshold_multiplier": 0.6,
        "max_pois_key": "c_max_pois",
        "filter": "core_indoor",
    },
}

VALID_CATEGORIES = {"food", "street", "mall", "attraction"}
VALID_CONFIDENCE = {"verified", "pending", "suspicious"}
VALID_TRIP_TYPES = set(TRIP_TYPE_PROFILES)
VALID_BUDGET = {"low", "mid", "high"}
VALID_ACTIVITIES = {
    "food",
    "street",
    "mall",
    "attraction",
    "nature",
    "hiking",
    "theme_park",
    "museum",
    "shopping",
    "nightlife",
    "show",
    "camping",
    "beach",
    "hotspring",
    "photo",
    "study",
    "family_park",
}

DEFAULT_OPTIONS = {
    "start_time": "09:30",
    "end_time": "21:00",
    "party": "general",
    "max_walk_km": 6.0,
    "walk_speed_kmh": 4.0,
    "taxi_speed_kmh": 22.0,
    "taxi_wait_min": 5.0,
    "taxi_threshold_km": 2.0,
    "cluster_radius_km": 1.5,
    "max_cluster_size": 8,
    "trip_type": "local_fullday",
    "budget_level": "mid",
    "experience_level": "novice",
}


class PlanError(Exception):
    """可预期的输入或规划错误。"""


def haversine_km(lat1, lng1, lat2, lng2):
    """两点球面距离（公里）。"""
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(a))


def parse_hhmm(value, field_name="time"):
    """'HH:MM' -> 当日分钟数。"""
    if not isinstance(value, str) or ":" not in value:
        raise PlanError(f"{field_name} 必须是 'HH:MM' 格式，收到: {value!r}")
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise PlanError(f"{field_name} 必须是 'HH:MM' 格式，收到: {value!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise PlanError(f"{field_name} 必须是 'HH:MM' 格式，收到: {value!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise PlanError(f"{field_name} 超出有效范围: {value!r}")
    return hour * 60 + minute


def fmt_hhmm(minutes):
    """当日分钟数 -> 'HH:MM'（跨日标注天数）。"""
    if minutes < 0:
        minutes = 0
    day_offset = minutes // (24 * 60)
    remainder = minutes % (24 * 60)
    text = f"{remainder // 60:02d}:{remainder % 60:02d}"
    if day_offset > 0:
        text = f"{text}(+{day_offset}d)"
    return text


def _distance(a, b):
    return haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])


def normalize_band(band):
    """接受 '0-3' 或 'A1' 两种写法。"""
    if band in AGE_PROFILES:
        return band
    if band in BAND_ALIASES:
        return BAND_ALIASES[band]
    raise PlanError(
        f"未知年龄段: {band!r}；可选 {sorted(AGE_PROFILES)} 或 {sorted(BAND_ALIASES)}"
    )


def load_input(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise PlanError(f"输入文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"输入 JSON 解析失败: {exc}") from exc
    return data


def validate_input(data):
    if not isinstance(data, dict):
        raise PlanError("输入顶层必须是 JSON 对象")
    pois = data.get("pois")
    if not isinstance(pois, list) or not pois:
        raise PlanError("pois 必须是非空数组")
    if len(pois) > 200:
        raise PlanError("pois 数量超过 200，请先按距离与类型筛选")

    seen_ids = set()
    for index, poi in enumerate(pois):
        prefix = f"pois[{index}]"
        if not isinstance(poi, dict):
            raise PlanError(f"{prefix} 必须是对象")
        for required in ("id", "name", "lat", "lng", "category", "dwell_min"):
            if required not in poi:
                raise PlanError(f"{prefix} 缺少必填字段: {required}")
        if not isinstance(poi["id"], str) or not poi["id"].strip():
            raise PlanError(f"{prefix}.id 必须是非空字符串")
        if poi["id"] in seen_ids:
            raise PlanError(f"{prefix}.id 重复: {poi['id']}")
        seen_ids.add(poi["id"])
        if not isinstance(poi["name"], str) or not poi["name"].strip():
            raise PlanError(f"{prefix}.name 必须是非空字符串")
        try:
            poi["lat"] = float(poi["lat"])
            poi["lng"] = float(poi["lng"])
        except (TypeError, ValueError) as exc:
            raise PlanError(f"{prefix} 坐标必须是数字") from exc
        if not (-90 <= poi["lat"] <= 90 and -180 <= poi["lng"] <= 180):
            raise PlanError(f"{prefix} 坐标超出有效范围")
        if poi["category"] not in VALID_CATEGORIES:
            raise PlanError(
                f"{prefix}.category 必须是 {sorted(VALID_CATEGORIES)} 之一，收到: {poi['category']!r}"
            )
        try:
            poi["dwell_min"] = int(poi["dwell_min"])
        except (TypeError, ValueError) as exc:
            raise PlanError(f"{prefix}.dwell_min 必须是整数") from exc
        if poi["dwell_min"] <= 0:
            raise PlanError(f"{prefix}.dwell_min 必须大于 0")
        if "confidence" in poi and poi["confidence"] not in VALID_CONFIDENCE:
            raise PlanError(
                f"{prefix}.confidence 必须是 {sorted(VALID_CONFIDENCE)} 之一"
            )
        if "tier" in poi and poi["tier"] not in {"core", "normal", "optional"}:
            raise PlanError(f"{prefix}.tier 必须是 core / normal / optional")
        if "closed_days" in poi:
            if not isinstance(poi["closed_days"], list) or any(
                not isinstance(day, int) or day < 0 or day > 6
                for day in poi["closed_days"]
            ):
                raise PlanError(f"{prefix}.closed_days 必须是 0-6 的整数数组")

    options = data.get("options", {})
    if not isinstance(options, dict):
        raise PlanError("options 必须是对象")
    merged = dict(DEFAULT_OPTIONS)
    merged.update(options)
    parse_hhmm(merged["start_time"], "options.start_time")
    parse_hhmm(merged["end_time"], "options.end_time")
    if merged["party"] not in PARTY_PROFILES:
        raise PlanError(
            f"options.party 必须是 {sorted(PARTY_PROFILES)} 之一，收到: {merged['party']!r}"
        )
    if merged["trip_type"] not in VALID_TRIP_TYPES:
        raise PlanError(
            f"options.trip_type 必须是 {sorted(VALID_TRIP_TYPES)} 之一，收到: {merged['trip_type']!r}"
        )
    if merged["budget_level"] not in VALID_BUDGET:
        raise PlanError(
            f"options.budget_level 必须是 {sorted(VALID_BUDGET)} 之一，收到: {merged['budget_level']!r}"
        )
    if merged.get("experience_level", "novice") not in EXPERIENCE_FACTORS:
        raise PlanError(
            f"options.experience_level 必须是 {sorted(EXPERIENCE_FACTORS)} 之一，"
            f"收到: {merged.get('experience_level')!r}"
        )
    activities = merged.get("activities", [])
    if not isinstance(activities, list) or any(
        activity not in VALID_ACTIVITIES for activity in activities
    ):
        raise PlanError(
            f"options.activities 必须是 {sorted(VALID_ACTIVITIES)} 的子集"
        )

    members = merged.get("members")
    if members is not None:
        if not isinstance(members, list) or not members:
            raise PlanError("options.members 必须是非空数组")
        for index, member in enumerate(members):
            prefix = f"options.members[{index}]"
            if not isinstance(member, dict) or "band" not in member:
                raise PlanError(f"{prefix} 必须包含 band")
            normalize_band(member["band"])
            try:
                count = int(member.get("count", 1))
            except (TypeError, ValueError) as exc:
                raise PlanError(f"{prefix}.count 必须是整数") from exc
            if count <= 0:
                raise PlanError(f"{prefix}.count 必须大于 0")

    for key in (
        "max_walk_km",
        "walk_speed_kmh",
        "taxi_speed_kmh",
        "taxi_wait_min",
        "taxi_threshold_km",
        "cluster_radius_km",
    ):
        try:
            merged[key] = float(merged[key])
        except (TypeError, ValueError) as exc:
            raise PlanError(f"options.{key} 必须是数字") from exc
        if merged[key] <= 0:
            raise PlanError(f"options.{key} 必须大于 0")
    merged["max_cluster_size"] = int(merged.get("max_cluster_size", 8))

    start_point = merged.get("start_point")
    if start_point is not None:
        if not isinstance(start_point, dict) or "lat" not in start_point or "lng" not in start_point:
            raise PlanError("options.start_point 必须是包含 lat / lng 的对象")
        try:
            start_point["lat"] = float(start_point["lat"])
            start_point["lng"] = float(start_point["lng"])
        except (TypeError, ValueError) as exc:
            raise PlanError("options.start_point 坐标必须是数字") from exc

    merged["_start_min"] = parse_hhmm(merged["start_time"], "options.start_time")
    merged["_end_min"] = parse_hhmm(merged["end_time"], "options.end_time")
    if merged["_end_min"] <= merged["_start_min"]:
        raise PlanError("options.end_time 必须晚于 options.start_time")
    return pois, merged


def resolve_party(options):
    """组合人群强度：最弱成员 × 经验安全系数；多代同游单独收紧。"""
    experience = options.get("experience_level", "novice")
    safety = EXPERIENCE_FACTORS.get(experience, 0.85)
    members = options.get("members")
    if members:
        factors = []
        buffers = []
        queues = []
        constraints = set()
        bands = []
        for member in members:
            band = normalize_band(member["band"])
            count = int(member.get("count", 1))
            profile = AGE_PROFILES[band]
            bands.append(band)
            for _ in range(count):
                factors.append(profile["walk_factor"])
                buffers.append(profile["buffer_ratio"])
                queues.append(profile["queue_tolerance_min"])
            constraints.update(profile["hard_constraints"])
        weakest_band = min(bands, key=lambda band: AGE_PROFILES[band]["walk_factor"])
        unique_bands = set(bands)
        multigenerational = bool(
            unique_bands & {"0-3", "4-6"} and "70+" in unique_bands
        )
        return {
            "walk_factor": round(min(factors) * safety, 4),
            "buffer_ratio": max(buffers),
            "queue_tolerance_min": min(queues),
            "hard_constraints": sorted(constraints),
            "weakest_band": weakest_band,
            "weakest_label": AGE_PROFILES[weakest_band]["label"],
            "is_composite": len(unique_bands) > 1,
            "multigenerational": multigenerational,
            "experience_level": experience,
            "safety_factor": safety,
        }

    band = PARTY_BAND_MAP.get(options.get("party", "general"), "36-50")
    profile = AGE_PROFILES[band]
    return {
        "walk_factor": profile["walk_factor"],
        "buffer_ratio": profile["buffer_ratio"],
        "queue_tolerance_min": profile["queue_tolerance_min"],
        "hard_constraints": sorted(profile["hard_constraints"]),
        "weakest_band": band,
        "weakest_label": profile["label"],
        "is_composite": False,
        "multigenerational": False,
        "experience_level": experience,
        "safety_factor": 1.0,
    }


def _split_by_closed_days(pois, travel_date, warnings, unassigned):
    kept = []
    weekday = travel_date.weekday()
    for poi in pois:
        closed_days = poi.get("closed_days") or []
        if weekday in closed_days:
            reason = f"闭馆日（周{weekday + 1}不开放）"
            warnings.append(f"{poi['name']}：{reason}，已从路线剔除")
            unassigned.append({"poi_id": poi["id"], "name": poi["name"], "reason": reason})
            continue
        kept.append(poi)
    return kept


def _cluster_with_anchors(pois, radius_km):
    anchors = [poi for poi in pois if poi.get("must_visit") or poi.get("tier") == "core"]
    if not anchors:
        return None
    clusters = [[anchor] for anchor in anchors]
    overflow = []
    for poi in pois:
        if poi.get("must_visit") or poi.get("tier") == "core":
            continue
        best_index = min(
            range(len(anchors)),
            key=lambda idx: _distance(poi, anchors[idx]),
        )
        if _distance(poi, anchors[best_index]) <= radius_km:
            clusters[best_index].append(poi)
        else:
            overflow.append(poi)
    if overflow:
        clusters.extend(_cluster_by_radius(overflow, radius_km))
    return clusters


def _cluster_by_radius(pois, radius_km):
    count = len(pois)
    parent = list(range(count))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i in range(count):
        for j in range(i + 1, count):
            if _distance(pois[i], pois[j]) <= radius_km:
                union(i, j)

    groups = {}
    for index in range(count):
        groups.setdefault(find(index), []).append(pois[index])
    return list(groups.values())


def cluster_pois(pois, options):
    clusters = _cluster_with_anchors(pois, options["cluster_radius_km"])
    if clusters is None:
        clusters = _cluster_by_radius(pois, options["cluster_radius_km"])
    return clusters


def _nearest_neighbor_open(points, start_point=None):
    remaining = list(range(len(points)))
    order = []
    if start_point is not None:
        current_index = min(
            remaining,
            key=lambda idx: haversine_km(
                start_point["lat"], start_point["lng"], points[idx]["lat"], points[idx]["lng"]
            ),
        )
    else:
        current_index = 0
    order.append(current_index)
    remaining.remove(current_index)
    while remaining:
        current = points[current_index]
        next_index = min(remaining, key=lambda idx: _distance(current, points[idx]))
        order.append(next_index)
        remaining.remove(next_index)
        current_index = next_index
    return order


def _two_opt(points, order):
    improved = True
    while improved:
        improved = False
        for i in range(1, len(order) - 1):
            for j in range(i + 1, len(order)):
                a = points[order[i - 1]]
                b = points[order[i]]
                c = points[order[j]]
                d = points[order[j + 1]] if j + 1 < len(order) else None
                before = _distance(a, b) + (_distance(c, d) if d is not None else 0.0)
                after = _distance(a, c) + (_distance(b, d) if d is not None else 0.0)
                if after + 1e-9 < before:
                    order[i : j + 1] = reversed(order[i : j + 1])
                    improved = True
    return order


def _held_karp_open(points, start_point=None):
    n = len(points)
    if n == 1:
        return [0]
    full = (1 << n) - 1
    inf = float("inf")
    dp = [[inf] * n for _ in range(1 << n)]
    parent = [[-1] * n for _ in range(1 << n)]
    for i in range(n):
        if start_point is None:
            dp[1 << i][i] = 0.0
        else:
            dp[1 << i][i] = haversine_km(
                start_point["lat"],
                start_point["lng"],
                points[i]["lat"],
                points[i]["lng"],
            )
    for mask in range(1 << n):
        for last in range(n):
            current = dp[mask][last]
            if current == inf:
                continue
            for nxt in range(n):
                if mask & (1 << nxt):
                    continue
                next_mask = mask | (1 << nxt)
                cost = current + _distance(points[last], points[nxt])
                if cost < dp[next_mask][nxt]:
                    dp[next_mask][nxt] = cost
                    parent[next_mask][nxt] = last
    best_last = min(range(n), key=lambda idx: dp[full][idx])
    order = []
    mask = full
    last = best_last
    while last != -1:
        order.append(last)
        previous = parent[mask][last]
        mask ^= 1 << last
        last = previous
    order.reverse()
    return order


def solve_open_tsp(points, start_point=None):
    if len(points) <= 1:
        return [0]
    if len(points) <= 10:
        return _held_karp_open(points, start_point)
    best_order = None
    best_cost = float("inf")
    for start_index in range(len(points)):
        rotated = points[start_index:] + points[:start_index]
        order = _two_opt(rotated, _nearest_neighbor_open(rotated))
        cost = sum(
            _distance(rotated[order[i]], rotated[order[i + 1]])
            for i in range(len(order) - 1)
        )
        if cost < best_cost:
            best_cost = cost
            best_order = [(start_index + idx) % len(points) for idx in order]
    return best_order


def _order_clusters(clusters, start_point):
    if len(clusters) <= 1:
        return list(range(len(clusters)))
    centroids = []
    for cluster in clusters:
        lat = sum(poi["lat"] for poi in cluster) / len(cluster)
        lng = sum(poi["lng"] for poi in cluster) / len(cluster)
        centroids.append({"lat": lat, "lng": lng})
    return _two_opt(centroids, _nearest_neighbor_open(centroids, start_point))


def _travel(distance_km, options, transport_modes):
    if distance_km <= 0:
        return "start", 0.0, 0
    threshold = options["taxi_threshold_km"]
    if distance_km <= threshold or "taxi" not in transport_modes:
        speed = options["walk_speed_kmh"]
        mode = "walk"
        minutes = distance_km / speed * 60.0
    else:
        speed = options["taxi_speed_kmh"]
        mode = "taxi"
        minutes = distance_km / speed * 60.0 + options["taxi_wait_min"]
    return mode, distance_km, int(round(minutes))


def trim_pois(pois, limit):
    """按档位上限裁剪，优先保留核心与室内点位。"""
    if len(pois) <= limit:
        return list(pois), []
    ranked = sorted(
        pois,
        key=lambda poi: (
            0 if (poi.get("must_visit") or poi.get("tier") == "core") else 1,
            0 if poi.get("indoor") else 1,
            0 if poi.get("confidence") == "verified" else 1,
        ),
    )
    return ranked[:limit], ranked[limit:]


def select_pois(pois, variant, trip_profile):
    filter_mode = variant["filter"]
    if filter_mode == "all":
        selected = list(pois)
    elif filter_mode == "no_optional":
        selected = [poi for poi in pois if poi.get("tier", "normal") != "optional"]
    else:
        selected = [
            poi
            for poi in pois
            if poi.get("tier") == "core" or poi.get("must_visit") or poi.get("indoor")
        ]
    if not selected:
        selected = list(pois)
    limit = trip_profile[variant["max_pois_key"]]
    return trim_pois(selected, limit)


def assemble_route(clusters, options, party_params, variant, trip_profile):
    warnings = []
    segments = []
    unassigned = []
    total_walk_km = 0.0
    total_distance_km = 0.0
    total_travel_min = 0
    total_visit_min = 0
    rest_inserted = False

    effective_max_walk = (
        options["max_walk_km"] * party_params["walk_factor"] * variant["walk_multiplier"]
    )
    party_max_walk = options["max_walk_km"] * party_params["walk_factor"]
    buffer_ratio = (
        party_params["buffer_ratio"]
        + variant["buffer_delta"]
        + trip_profile.get("buffer_delta", 0.0)
    )
    if party_params.get("multigenerational"):
        buffer_ratio = max(buffer_ratio, MULTIGENERATIONAL_PROFILE["buffer_floor"])
    buffer_ratio = max(0.05, buffer_ratio)
    rest_protected_min = (
        MULTIGENERATIONAL_PROFILE["rest_protected_min"]
        if party_params.get("multigenerational")
        else 0
    )
    local_options = dict(options)
    local_options["taxi_threshold_km"] = (
        options["taxi_threshold_km"] * variant["taxi_threshold_multiplier"]
    )

    transport_modes = options.get("transport") or ["walk", "metro", "taxi"]
    if not isinstance(transport_modes, list):
        raise PlanError("options.transport 必须是数组")

    hard_constraints = set(party_params["hard_constraints"])
    start_point = options.get("start_point")
    cluster_order = _order_clusters(clusters, start_point)
    current_min = options["_start_min"]
    previous_point = start_point
    order_counter = 1

    for cluster_index in cluster_order:
        cluster = clusters[cluster_index]
        if len(cluster) > options["max_cluster_size"]:
            warnings.append(
                f"簇 {cluster_index + 1} 含 {len(cluster)} 个点位，超过建议上限 "
                f"{options['max_cluster_size']}，建议拆成两个半场"
            )
        local_order = solve_open_tsp(cluster, previous_point)
        for local_index in local_order:
            poi = cluster[local_index]
            if "avoid_stairs" in hard_constraints and (
                poi.get("has_stairs") or int(poi.get("step_count", 0) or 0) > 0
            ):
                warnings.append(
                    f"{poi['name']}：含台阶/爬升，与同行人的'避免台阶'约束冲突，"
                    f"建议替换为平缓点位或只安排外围"
                )
            if int(poi.get("queue_min", 0) or 0) > party_params["queue_tolerance_min"]:
                warnings.append(
                    f"{poi['name']}：预计排队 {poi['queue_min']} 分钟，超过同行人可接受上限 "
                    f"{party_params['queue_tolerance_min']} 分钟，建议错峰或换备选"
                )

            if previous_point is None:
                distance, mode, travel_min = 0.0, "start", 0
            else:
                distance = haversine_km(
                    previous_point["lat"],
                    previous_point["lng"],
                    poi["lat"],
                    poi["lng"],
                )
                mode, distance, travel_min = _travel(distance, local_options, transport_modes)
            arrive = current_min + travel_min
            wait_min = 0
            if poi.get("open_time"):
                open_min = parse_hhmm(poi["open_time"], f"{poi['name']}.open_time")
                if arrive < open_min:
                    wait_min = open_min - arrive
                    arrive = open_min
            depart = arrive + poi["dwell_min"]

            if poi.get("close_time"):
                close_min = parse_hhmm(poi["close_time"], f"{poi['name']}.close_time")
                if depart > close_min:
                    warnings.append(
                        f"{poi['name']}：预计 {fmt_hhmm(depart)} 离开，"
                        f"但 {poi['close_time']} 关门，需压缩停留或提前到达"
                    )
            if wait_min >= 45:
                warnings.append(
                    f"{poi['name']}：到达后需等待 {wait_min} 分钟才开门，建议调整顺序或先去附近点位"
                )

            segments.append(
                {
                    "order": order_counter,
                    "poi_id": poi["id"],
                    "name": poi["name"],
                    "category": poi["category"],
                    "tier": poi.get("tier", "normal"),
                    "cluster": cluster_index + 1,
                    "arrive": fmt_hhmm(arrive),
                    "depart": fmt_hhmm(depart),
                    "travel_from_prev_km": round(distance, 2),
                    "travel_mode": mode,
                    "travel_min": travel_min,
                    "wait_min": wait_min,
                    "dwell_min": poi["dwell_min"],
                    "confidence": poi.get("confidence", "pending"),
                    "verified_at": poi.get("verified_at"),
                    "indoor": bool(poi.get("indoor", False)),
                    "note": poi.get("note", ""),
                }
            )
            order_counter += 1
            total_visit_min += poi["dwell_min"]
            total_travel_min += travel_min
            total_distance_km += distance
            if mode == "walk":
                total_walk_km += distance
            current_min = depart
            previous_point = poi
            if rest_protected_min and not rest_inserted and current_min >= 12 * 60:
                segments.append(
                    {
                        "order": order_counter,
                        "poi_id": "__rest__",
                        "name": "午休/落座休息（多代同游强制保护区）",
                        "category": "rest",
                        "tier": "core",
                        "cluster": cluster_index + 1,
                        "arrive": fmt_hhmm(current_min),
                        "depart": fmt_hhmm(current_min + rest_protected_min),
                        "travel_from_prev_km": 0.0,
                        "travel_mode": "rest",
                        "travel_min": 0,
                        "wait_min": 0,
                        "dwell_min": rest_protected_min,
                        "confidence": "verified",
                        "verified_at": None,
                        "indoor": True,
                        "note": "12:00–14:30 不排程；老人回酒店或商场落座，孩子午睡",
                    }
                )
                current_min += rest_protected_min
                order_counter += 1
                rest_inserted = True

    buffer_min = int(round((total_visit_min + total_travel_min) * buffer_ratio))
    return_travel_min = 0
    if previous_point is not None and start_point is not None:
        return_distance = haversine_km(
            previous_point["lat"],
            previous_point["lng"],
            start_point["lat"],
            start_point["lng"],
        )
        _, _, return_travel_min = _travel(return_distance, local_options, transport_modes)
    return_deadline = current_min + return_travel_min
    rest_inserted_min = rest_protected_min if rest_inserted else 0
    total_min = total_visit_min + total_travel_min + buffer_min + rest_inserted_min
    projected_end = options["_start_min"] + total_min
    total_pois = sum(1 for segment in segments if segment["category"] != "rest")
    indoor_count = sum(
        1 for segment in segments if segment["indoor"] and segment["category"] != "rest"
    )
    indoor_ratio = round(indoor_count / total_pois, 2) if total_pois else 0.0

    if party_params.get("multigenerational"):
        if rest_inserted:
            warnings.append(
                f"多代同游：12:00–14:30 为强制休息保护区，已在时间轴插入 "
                f"{rest_inserted_min} 分钟午休段；建议老人回酒店或商场落座、孩子午睡，"
                f"成人可短程自由活动并约定汇合点"
            )
        else:
            warnings.append(
                "多代同游：行程在 12:00 前结束，未触发午休保护区；"
                "如延长到下午，请手动保留 12:00–14:30"
            )
    if total_walk_km > effective_max_walk + 1e-9:
        warnings.append(
            f"总步行 {total_walk_km:.1f} km 超过本档上限 "
            f"{effective_max_walk:.1f} km，建议减少同簇点位或改打车"
        )
    if projected_end > options["_end_min"]:
        warnings.append(
            f"含缓冲预计 {fmt_hhmm(projected_end)} 结束，晚于设定结束时间 "
            f"{options['end_time']}，需删减点位或压缩停留"
        )
    if return_deadline > options["_end_min"]:
        warnings.append(
            f"最晚返程 {fmt_hhmm(return_deadline)} 晚于结束时间 {options['end_time']}，注意末班车"
        )
    if "needs_indoor" in hard_constraints and indoor_ratio < 0.25:
        warnings.append(
            f"同行人含'需要室内备选'约束，但室内点位占比仅 {int(indoor_ratio * 100)}%，"
            f"建议替换 1 个室内点位（商场/博物馆/咖啡馆）"
        )
    if (
        variant["priority"] == 1
        and party_params["weakest_band"] in {"0-3", "4-6", "61-70", "70+"}
    ):
        warnings.append(
            f"尽兴版强度高于最弱成员（{party_params['weakest_label']}）的舒适上限，"
            f"不建议全员参加；建议分成两线：体力好的走尽兴线，最弱成员走省心线并约定汇合点"
        )

    summary = {
        "date": options.get("date"),
        "trip_type": options.get("trip_type", "local_fullday"),
        "budget_level": options.get("budget_level", "mid"),
        "party_type": options["party"],
        "party": options["party"],
        "weakest_band": party_params["weakest_band"],
        "weakest_label": party_params["weakest_label"],
        "hard_constraints": party_params["hard_constraints"],
        "queue_tolerance_min": party_params["queue_tolerance_min"],
        "total_pois": total_pois,
        "total_distance_km": round(total_distance_km, 2),
        "total_walk_km": round(total_walk_km, 2),
        "visit_min": total_visit_min,
        "travel_min": total_travel_min,
        "buffer_min": buffer_min,
        "total_min": total_min,
        "start_time": options["start_time"],
        "end_time": options["end_time"],
        "projected_end": fmt_hhmm(projected_end),
        "return_deadline": fmt_hhmm(return_deadline),
        "within_window": projected_end <= options["_end_min"],
        "party_max_walk_km": round(party_max_walk, 2),
        "effective_max_walk_km": round(effective_max_walk, 2),
        "indoor_ratio": indoor_ratio,
        "experience_level": party_params.get("experience_level", "novice"),
        "multigenerational": party_params.get("multigenerational", False),
        "rest_protected_min": rest_inserted_min,
    }
    return summary, segments, warnings, unassigned


def _prepare(data):
    pois, options = validate_input(data)
    travel_date = date.today()
    if options.get("date"):
        try:
            travel_date = date.fromisoformat(str(options["date"]))
        except ValueError as exc:
            raise PlanError(f"options.date 必须是 YYYY-MM-DD，收到: {options['date']!r}") from exc

    warnings = []
    unassigned = []
    available = _split_by_closed_days(pois, travel_date, warnings, unassigned)
    if not available:
        raise PlanError("所有点位在当天都闭馆，无法规划路线")
    party_params = resolve_party(options)
    return available, options, travel_date, warnings, unassigned, party_params


def _build_plan(available, options, party_params, variant_key, base_warnings, base_unassigned):
    variant = dict(VARIANTS[variant_key])
    trip_profile = dict(TRIP_TYPE_PROFILES[options["trip_type"]])
    if party_params.get("multigenerational"):
        variant["walk_multiplier"] = min(
            variant["walk_multiplier"], MULTIGENERATIONAL_PROFILE["a_walk_cap"]
        )
        variant["taxi_threshold_multiplier"] = min(
            variant["taxi_threshold_multiplier"], 0.6
        )
        trip_profile["a_max_pois"] = min(
            trip_profile["a_max_pois"], MULTIGENERATIONAL_PROFILE["a_max_pois"]
        )
        trip_profile["b_max_pois"] = min(
            trip_profile["b_max_pois"], MULTIGENERATIONAL_PROFILE["b_max_pois"]
        )
        trip_profile["c_max_pois"] = min(
            trip_profile["c_max_pois"], MULTIGENERATIONAL_PROFILE["c_max_pois"]
        )
    selected, dropped = select_pois(available, variant, trip_profile)
    clusters = cluster_pois(selected, options)
    summary, segments, warnings, unassigned = assemble_route(
        clusters, options, party_params, variant, trip_profile
    )
    warnings = list(base_warnings) + warnings
    dropped_items = [
        {
            "poi_id": poi["id"],
            "name": poi["name"],
            "reason": f"{variant['name']}按档位上限裁剪（本档最多 {trip_profile[variant['max_pois_key']]} 个点位）",
        }
        for poi in dropped
    ]
    selected_ids = {poi["id"] for poi in selected}
    dropped_ids = {poi["id"] for poi in dropped}
    excluded_items = [
        {
            "poi_id": poi["id"],
            "name": poi["name"],
            "reason": "本档未排入（可选点位或类型/风险过滤）",
        }
        for poi in available
        if poi["id"] not in selected_ids and poi["id"] not in dropped_ids
    ]
    unassigned = list(base_unassigned) + dropped_items + excluded_items + unassigned

    suspicious = [
        poi["name"] for poi in selected if poi.get("confidence") == "suspicious"
    ]
    if suspicious:
        warnings.append(
            "以下点位置信度为存疑，建议出行前核实后再进主路线：" + "、".join(suspicious)
        )
    if len(selected) < len(available):
        warnings.append(
            f"{variant['name']}共筛选 {len(selected)} 个点位，其余 {len(available) - len(selected)} 个"
            f"因档位上限或类型过滤未排入，可在其他档位查看"
        )

    summary["date"] = travel_date_str(options)
    summary["plan_key"] = variant_key
    summary["plan_name"] = variant["name"]
    summary["plan_slogan"] = variant["slogan"]
    return {
        "key": variant_key,
        "name": variant["name"],
        "slogan": variant["slogan"],
        "priority": variant["priority"],
        "summary": summary,
        "segments": segments,
        "warnings": warnings,
        "unassigned": unassigned,
    }


def travel_date_str(options):
    if options.get("date"):
        return str(options["date"])
    return date.today().isoformat()


def build_comparison(plans):
    rows = []
    for plan in plans:
        summary = plan["summary"]
        rows.append(
            {
                "plan": plan["key"],
                "name": plan["name"],
                "slogan": plan["slogan"],
                "priority": plan["priority"],
                "pois": summary["total_pois"],
                "walk_km": summary["total_walk_km"],
                "buffer_min": summary["buffer_min"],
                "total_min": summary["total_min"],
                "indoor_ratio": summary["indoor_ratio"],
                "effective_max_walk_km": summary["effective_max_walk_km"],
                "within_window": summary["within_window"],
                "return_deadline": summary["return_deadline"],
            }
        )
    return {
        "columns": [
            "plan",
            "name",
            "pois",
            "walk_km",
            "buffer_min",
            "total_min",
            "indoor_ratio",
            "within_window",
            "return_deadline",
        ],
        "rows": rows,
    }


def plan(data):
    """单方案（默认 B 舒适版），保持向后兼容。"""
    available, options, _travel_date, warnings, unassigned, party_params = _prepare(data)
    result = _build_plan(
        available, options, party_params, "B", warnings, unassigned
    )
    return {
        "status": "success",
        "summary": result["summary"],
        "segments": result["segments"],
        "warnings": result["warnings"],
        "unassigned": result["unassigned"],
    }


def plan_variants(data, count=3):
    """生成 A/B/C 多档方案。"""
    count = max(1, min(3, int(count)))
    available, options, _travel_date, warnings, unassigned, party_params = _prepare(data)
    plans = []
    for key in list(VARIANTS.keys())[:count]:
        plans.append(
            _build_plan(available, options, party_params, key, warnings, unassigned)
        )
    return {
        "status": "success",
        "trip": {
            "type": options.get("trip_type", "local_fullday"),
            "budget_level": options.get("budget_level", "mid"),
            "date": travel_date_str(options),
        },
        "party": {
            "type": options["party"],
            "walk_factor": party_params["walk_factor"],
            "buffer_ratio": party_params["buffer_ratio"],
            "weakest_band": party_params["weakest_band"],
            "weakest_label": party_params["weakest_label"],
            "hard_constraints": party_params["hard_constraints"],
            "queue_tolerance_min": party_params["queue_tolerance_min"],
            "experience_level": party_params.get("experience_level", "novice"),
            "multigenerational": party_params.get("multigenerational", False),
        },
        "comparison": build_comparison(plans),
        "plans": plans,
    }


def main():
    parser = argparse.ArgumentParser(
        description="城市出行路线装配与 ABC 三档方案生成"
    )
    parser.add_argument("--input", required=True, help="输入 itinerary JSON 路径")
    parser.add_argument("--output", help="输出 route JSON 路径；不填则打印到 stdout")
    parser.add_argument(
        "--plans",
        type=int,
        default=3,
        choices=[1, 3],
        help="生成方案档数：3=ABC 三档（默认），1=仅 B 舒适版",
    )
    args = parser.parse_args()

    try:
        data = load_input(args.input)
        if args.plans >= 3:
            result = plan_variants(data, 3)
        else:
            result = plan(data)
    except PlanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        except OSError as exc:
            print(f"ERROR: 无法写入输出文件 {args.output}: {exc}", file=sys.stderr)
            return 2
        summary = {
            "status": "success",
            "output": args.output,
            "plans": len(result.get("plans", [])),
            "segments": len(result.get("segments", [])),
        }
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())