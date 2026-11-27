#!/usr/bin/env python3
"""fetch_pois.py 的非网络单元测试。

只验证参数解析与凭证缺失时的错误行为，不发起网络请求。
真实检索能力由端到端运行验证（Photon / 高德 / 百度）。
"""

import importlib.util
import os
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_DIR / "scripts" / "fetch_pois.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("fetch_pois", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_pois = _load_module()


class TestParseQuery(unittest.TestCase):
    def test_with_category(self):
        self.assertEqual(fetch_pois.parse_query("人民公园:attraction"), ("人民公园", "attraction"))

    def test_without_category(self):
        self.assertEqual(fetch_pois.parse_query("宽窄巷子"), ("宽窄巷子", None))

    def test_invalid_category(self):
        with self.assertRaises(fetch_pois.FetchError):
            fetch_pois.parse_query("人民公园:nightclub")

    def test_empty_queries(self):
        with self.assertRaises(fetch_pois.FetchError):
            fetch_pois.validate_queries([])


class TestCredentials(unittest.TestCase):
    def setUp(self):
        self._amap = os.environ.pop("AMAP_KEY", None)
        self._baidu = os.environ.pop("BAIDU_MAP_AK", None)

    def tearDown(self):
        if self._amap is not None:
            os.environ["AMAP_KEY"] = self._amap
        if self._baidu is not None:
            os.environ["BAIDU_MAP_AK"] = self._baidu

    def test_amap_missing_key(self):
        with self.assertRaises(fetch_pois.FetchError):
            fetch_pois.fetch_amap("宽窄巷子", "成都", 1)

    def test_baidu_missing_ak(self):
        with self.assertRaises(fetch_pois.FetchError):
            fetch_pois.fetch_baidu("宽窄巷子", "成都", 1)


class TestCategoryMapping(unittest.TestCase):
    def test_osm_mall(self):
        self.assertEqual(
            fetch_pois.map_osm_category({"osm_key": "shop", "osm_value": "mall"}), "mall"
        )

    def test_osm_food(self):
        self.assertEqual(
            fetch_pois.map_osm_category({"osm_key": "amenity", "osm_value": "restaurant"}),
            "food",
        )

    def test_osm_unknown(self):
        self.assertIsNone(
            fetch_pois.map_osm_category({"osm_key": "highway", "osm_value": "motorway"})
        )


if __name__ == "__main__":
    unittest.main()