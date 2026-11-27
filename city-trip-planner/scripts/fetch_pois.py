#!/usr/bin/env python3
"""fetch_pois.py — 从真实数据源检索 POI，输出标准 pois[] 片段

Provider:
  photon  默认，OpenStreetMap 数据，无需凭证（WGS84）
  amap    高德 Web 服务，需要环境变量 AMAP_KEY（GCJ02）
  baidu   百度地图，需要环境变量 BAIDU_MAP_AK（BD09）

职责：
  - 只做真实数据检索与字段映射，不生成任何虚构 POI。
  - 输出可直接并入 itinerary JSON 的 pois[]，营业时间缺失时置 null 并标 pending。
  - 不同 provider 坐标系不同，混合使用会产生偏移，_meta 中显式标注。

用法：
  python fetch_pois.py --city 成都 \
    --query "人民公园:attraction" --query "成都博物馆:attraction" \
    --output pois.json

  # os.environ 中配置 AMAP_KEY 后
  python fetch_pois.py --provider amap --city 成都 --query "宽窄巷子:street"
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

USER_AGENT = "city-trip-planner/1.0 (local skill; POI retrieval)"
PROVIDERS = {"photon", "amap", "baidu"}
CATEGORY_DEFAULTS = {
    "food": {"dwell_min": 75},
    "street": {"dwell_min": 60},
    "mall": {"dwell_min": 60},
    "attraction": {"dwell_min": 90},
}
COORDINATE_SYSTEMS = {"photon": "WGS84", "amap": "GCJ02", "baidu": "BD09"}


class FetchError(Exception):
    """可预期的检索错误。"""


def http_get_json(url, timeout=15, retries=1):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # 保留原始错误，重试后抛出
            last_error = exc
            if attempt < retries:
                time.sleep(1.0)
    raise FetchError(f"请求失败: {last_error}")


def parse_query(spec):
    if ":" in spec:
        name, category = spec.rsplit(":", 1)
        category = category.strip()
        if category not in CATEGORY_DEFAULTS:
            raise FetchError(
                f"query 类别必须是 {sorted(CATEGORY_DEFAULTS)} 之一，收到: {category!r}"
            )
        return name.strip(), category
    return spec.strip(), None


def pick_feature(features, city):
    if city:
        matched = [
            feature
            for feature in features
            if city in (feature.get("properties", {}).get("city") or "")
            or city in (feature.get("properties", {}).get("state") or "")
        ]
        if matched:
            return matched[0]
    return features[0] if features else None


def map_osm_category(properties):
    osm_key = properties.get("osm_key")
    osm_value = properties.get("osm_value")
    if osm_key == "shop" and osm_value in {"mall", "department_store"}:
        return "mall"
    if osm_key == "amenity" and osm_value in {
        "restaurant",
        "cafe",
        "fast_food",
        "food_court",
        "marketplace",
    }:
        return "food"
    if osm_key == "tourism" and osm_value in {"attraction", "museum", "gallery"}:
        return "attraction"
    if osm_key == "highway" and osm_value in {"pedestrian", "living_street"}:
        return "street"
    return None


def fetch_photon(name, city, limit):
    params = {"q": name, "limit": limit}
    url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode(params)
    data = http_get_json(url)
    feature = pick_feature(data.get("features", []), city)
    if feature is None:
        raise FetchError(f"Photon 未找到: {name}")
    properties = feature.get("properties", {})
    lng, lat = feature["geometry"]["coordinates"][:2]
    address_parts = [
        properties.get("street"),
        properties.get("locality"),
        properties.get("district"),
        properties.get("city"),
    ]
    return {
        "name": properties.get("name") or name,
        "lat": round(float(lat), 6),
        "lng": round(float(lng), 6),
        "category": map_osm_category(properties),
        "address": " / ".join(part for part in address_parts if part),
        "open_time": None,
        "close_time": None,
        "source": "photon:osm",
        "confidence": "pending",
        "note": "OpenStreetMap 数据；营业时间与运营状态需出行前核实",
    }


def map_amap_category(type_text):
    if not type_text:
        return None
    if "餐饮" in type_text:
        return "food"
    if "购物" in type_text:
        return "mall"
    if "风景名胜" in type_text or "博物馆" in type_text:
        return "attraction"
    if "地名地址" in type_text or "道路" in type_text:
        return "street"
    return None


def fetch_amap(name, city, limit):
    key = os.environ.get("AMAP_KEY")
    if not key:
        raise FetchError("未配置环境变量 AMAP_KEY，无法使用高德 provider")
    params = {
        "keywords": name,
        "city": city or "",
        "offset": limit,
        "page": 1,
        "extensions": "all",
        "key": key,
    }
    url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode(params)
    data = http_get_json(url)
    if str(data.get("status")) != "1":
        raise FetchError(f"高德返回错误: {data.get('info')} ({data.get('infocode')})")
    pois = data.get("pois") or []
    if not pois:
        raise FetchError(f"高德未找到: {name}")
    poi = pois[0]
    lng, lat = poi.get("location", "").split(",")
    biz_ext = poi.get("biz_ext") or {}
    open_time = biz_ext.get("open_time") or None
    return {
        "name": poi.get("name") or name,
        "lat": round(float(lat), 6),
        "lng": round(float(lng), 6),
        "category": map_amap_category(poi.get("type")),
        "address": poi.get("address") or "",
        "open_time": open_time,
        "close_time": None,
        "source": "amap",
        "confidence": "pending",
        "note": "高德 POI；营业时间以官方与现场为准",
    }


def map_baidu_category(type_text):
    if not type_text:
        return None
    if "美食" in type_text or "餐饮" in type_text:
        return "food"
    if "购物" in type_text:
        return "mall"
    if "景点" in type_text or "博物馆" in type_text:
        return "attraction"
    return None


def fetch_baidu(name, city, limit):
    ak = os.environ.get("BAIDU_MAP_AK")
    if not ak:
        raise FetchError("未配置环境变量 BAIDU_MAP_AK，无法使用百度 provider")
    params = {
        "query": name,
        "region": city or "",
        "output": "json",
        "page_size": limit,
        "ak": ak,
    }
    url = "https://api.map.baidu.com/place/v2/search?" + urllib.parse.urlencode(params)
    data = http_get_json(url)
    if data.get("status") != 0:
        raise FetchError(f"百度返回错误: {data.get('message')} ({data.get('status')})")
    results = data.get("results") or []
    if not results:
        raise FetchError(f"百度未找到: {name}")
    poi = results[0]
    location = poi.get("location") or {}
    detail = poi.get("detail_info") or {}
    return {
        "name": poi.get("name") or name,
        "lat": round(float(location.get("lat")), 6),
        "lng": round(float(location.get("lng")), 6),
        "category": map_baidu_category(detail.get("type")),
        "address": poi.get("address") or "",
        "open_time": None,
        "close_time": None,
        "source": "baidu",
        "confidence": "pending",
        "note": "百度 POI；营业时间以官方与现场为准",
    }


FETCHERS = {"photon": fetch_photon, "amap": fetch_amap, "baidu": fetch_baidu}


def build_pois(provider, city, queries, limit):
    fetcher = FETCHERS[provider]
    pois = []
    for index, spec in enumerate(queries, start=1):
        name, category = parse_query(spec)
        record = fetcher(name, city, limit)
        record["category"] = category or record.get("category") or "attraction"
        record["tier"] = "normal"
        record["dwell_min"] = CATEGORY_DEFAULTS[record["category"]]["dwell_min"]
        record["must_visit"] = False
        record["id"] = f"{provider}-{index}"
        record["verified_at"] = date.today().isoformat()
        record["query"] = name
        pois.append(record)
        time.sleep(0.5 if provider == "photon" else 0.2)
    return pois


def validate_queries(queries):
    if not queries:
        raise FetchError("至少提供一个 --query")
    for spec in queries:
        name, _ = parse_query(spec)
        if not name:
            raise FetchError(f"--query 名称不能为空: {spec!r}")


def main():
    parser = argparse.ArgumentParser(
        description="从真实数据源检索 POI，输出标准 pois[] 片段"
    )
    parser.add_argument(
        "--provider", default="photon", choices=sorted(PROVIDERS), help="数据源"
    )
    parser.add_argument("--city", default="", help="城市名，用于结果过滤")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="检索项，格式 '名称:类别'，类别 food/street/mall/attraction；可重复",
    )
    parser.add_argument("--limit", type=int, default=5, help="每个 query 的候选数")
    parser.add_argument("--output", help="输出 JSON 路径；不填则打印到 stdout")
    args = parser.parse_args()

    try:
        validate_queries(args.query)
        if args.limit <= 0:
            raise FetchError("--limit 必须大于 0")
        pois = build_pois(args.provider, args.city, args.query, args.limit)
    except FetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    result = {
        "_meta": {
            "provider": args.provider,
            "coordinate_system": COORDINATE_SYSTEMS[args.provider],
            "city": args.city,
            "fetched_at": date.today().isoformat(),
            "note": "真实数据源检索结果；营业时间与运营状态需出行前核实。不同 provider 坐标系不同，禁止混用。",
        },
        "pois": pois,
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        except OSError as exc:
            print(f"ERROR: 无法写入 {args.output}: {exc}", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "status": "success",
                    "output": args.output,
                    "provider": args.provider,
                    "pois": len(pois),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())