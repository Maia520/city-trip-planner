#!/usr/bin/env python3
"""plan_route.py 的单元测试。

测试数据来自 evals/fixtures/pois.mock.json，文件内已标记 TEST DATA ONLY。
测试只验证确定性算法，不代表真实 POI 数据或生产结果。
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts" / "plan_route.py"
FIXTURE_PATH = SKILL_DIR / "evals" / "fixtures" / "pois.mock.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("plan_route", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan_route = _load_module()


def load_fixture():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


class TestGeo(unittest.TestCase):
    def test_haversine_zero(self):
        self.assertAlmostEqual(plan_route.haversine_km(30.0, 104.0, 30.0, 104.0), 0.0, places=6)

    def test_haversine_known_scale(self):
        distance = plan_route.haversine_km(30.0, 104.0, 30.01, 104.0)
        self.assertGreater(distance, 1.0)
        self.assertLess(distance, 1.2)

    def test_parse_and_format_time(self):
        self.assertEqual(plan_route.parse_hhmm("09:30"), 570)
        self.assertEqual(plan_route.fmt_hhmm(570), "09:30")

    def test_invalid_time_raises(self):
        with self.assertRaises(plan_route.PlanError):
            plan_route.parse_hhmm("25:99")


class TestTsp(unittest.TestCase):
    def test_collinear_open_tsp(self):
        points = [
            {"lat": 0.0, "lng": 0.0},
            {"lat": 0.0, "lng": 0.01},
            {"lat": 0.0, "lng": 0.02},
        ]
        order = plan_route.solve_open_tsp(points)
        self.assertEqual(order[1], 1)
        self.assertIn(order, ([0, 1, 2], [2, 1, 0]))

    def test_open_tsp_respects_start_point(self):
        points = [
            {"lat": 0.0, "lng": 0.02},
            {"lat": 0.0, "lng": 0.0},
            {"lat": 0.0, "lng": 0.01},
        ]
        start = {"lat": 0.0, "lng": -0.001}
        order = plan_route.solve_open_tsp(points, start)
        self.assertEqual(order[0], 1)
        self.assertEqual(order[-1], 0)

    def test_single_point(self):
        self.assertEqual(plan_route.solve_open_tsp([{"lat": 0.0, "lng": 0.0}]), [0])


class TestAgeProfiles(unittest.TestCase):
    def test_normalize_band_alias(self):
        self.assertEqual(plan_route.normalize_band("A10"), "70+")
        self.assertEqual(plan_route.normalize_band("61-70"), "61-70")

    def test_weakest_member_rule(self):
        options = {
            "party": "general",
            "members": [
                {"band": "18-25", "count": 2},
                {"band": "70+", "count": 1},
            ],
        }
        party = plan_route.resolve_party(options)
        expected = plan_route.AGE_PROFILES["70+"]["walk_factor"] * 0.85
        self.assertAlmostEqual(party["walk_factor"], expected, places=4)
        self.assertEqual(party["weakest_band"], "70+")
        self.assertIn("avoid_stairs", party["hard_constraints"])
        self.assertTrue(party["is_composite"])

    def test_legacy_party_fallback(self):
        party = plan_route.resolve_party({"party": "elderly"})
        self.assertEqual(party["weakest_band"], "70+")
        self.assertFalse(party["is_composite"])

    def test_multigenerational_detection(self):
        party = plan_route.resolve_party(
            {
                "party": "general",
                "members": [
                    {"band": "36-50", "count": 2},
                    {"band": "70+", "count": 2},
                    {"band": "4-6", "count": 1},
                ],
            }
        )
        self.assertTrue(party["multigenerational"])
        self.assertEqual(party["weakest_band"], "70+")

    def test_experienced_raises_factor(self):
        members = [{"band": "70+", "count": 1}]
        novice = plan_route.resolve_party(
            {"party": "general", "members": members, "experience_level": "novice"}
        )
        experienced = plan_route.resolve_party(
            {"party": "general", "members": members, "experience_level": "experienced"}
        )
        self.assertGreater(experienced["walk_factor"], novice["walk_factor"])
        self.assertAlmostEqual(
            experienced["walk_factor"],
            plan_route.AGE_PROFILES["70+"]["walk_factor"] * 0.92,
            places=4,
        )

    def test_invalid_experience_level(self):
        data = load_fixture()
        data["options"]["experience_level"] = "expert"
        with self.assertRaises(plan_route.PlanError):
            plan_route.plan(data)


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture()

    def test_plan_success_and_closed_day(self):
        result = plan_route.plan(self.data)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["plan_key"], "B")
        self.assertEqual(len(result["segments"]), 4)
        unassigned_ids = {item["poi_id"] for item in result["unassigned"]}
        self.assertIn("t6", unassigned_ids)

    def test_two_clusters(self):
        result = plan_route.plan(self.data)
        clusters = {segment["cluster"] for segment in result["segments"]}
        self.assertEqual(len(clusters), 2)

    def test_segments_time_monotonic(self):
        result = plan_route.plan(self.data)
        departures = [
            plan_route.parse_hhmm(segment["depart"]) for segment in result["segments"]
        ]
        self.assertEqual(departures, sorted(departures))

    def test_summary_has_four_numbers(self):
        summary = plan_route.plan(self.data)["summary"]
        for key in ("total_walk_km", "buffer_min", "return_deadline", "within_window"):
            self.assertIn(key, summary)

    def test_suspicious_confidence_warning(self):
        self.data["pois"][1]["confidence"] = "suspicious"
        result = plan_route.plan(self.data)
        self.assertTrue(any("存疑" in warning for warning in result["warnings"]))

    def test_invalid_category_raises(self):
        self.data["pois"][0]["category"] = "nightclub"
        with self.assertRaises(plan_route.PlanError):
            plan_route.plan(self.data)

    def test_empty_pois_raises(self):
        self.data["pois"] = []
        with self.assertRaises(plan_route.PlanError):
            plan_route.plan(self.data)

    def test_over_walk_limit_warns(self):
        self.data["options"]["max_walk_km"] = 0.1
        result = plan_route.plan(self.data)
        self.assertTrue(any("超过" in warning for warning in result["warnings"]))

    def test_hard_constraint_stairs_warning(self):
        result = plan_route.plan(self.data)
        self.assertTrue(any("台阶" in warning for warning in result["warnings"]))

    def test_queue_tolerance_warning(self):
        result = plan_route.plan(self.data)
        self.assertTrue(any("排队" in warning for warning in result["warnings"]))


class TestVariants(unittest.TestCase):
    def setUp(self):
        self.data = load_fixture()

    def test_three_plans_generated(self):
        result = plan_route.plan_variants(self.data, 3)
        self.assertEqual(result["status"], "success")
        self.assertEqual([plan["key"] for plan in result["plans"]], ["A", "B", "C"])
        self.assertEqual(len(result["comparison"]["rows"]), 3)

    def test_variant_a_not_fewer_than_c(self):
        result = plan_route.plan_variants(self.data, 3)
        plans = {plan["key"]: plan for plan in result["plans"]}
        self.assertGreaterEqual(
            plans["A"]["summary"]["total_pois"], plans["C"]["summary"]["total_pois"]
        )

    def test_variant_c_indoor_ratio_highest(self):
        result = plan_route.plan_variants(self.data, 3)
        plans = {plan["key"]: plan for plan in result["plans"]}
        self.assertGreaterEqual(
            plans["C"]["summary"]["indoor_ratio"], plans["B"]["summary"]["indoor_ratio"]
        )

    def test_variant_a_warns_for_weak_member(self):
        result = plan_route.plan_variants(self.data, 3)
        plans = {plan["key"]: plan for plan in result["plans"]}
        self.assertTrue(any("不建议全员参加" in warning for warning in plans["A"]["warnings"]))

    def test_comparison_has_comparable_columns(self):
        result = plan_route.plan_variants(self.data, 3)
        columns = result["comparison"]["columns"]
        for column in ("pois", "walk_km", "indoor_ratio", "within_window"):
            self.assertIn(column, columns)

    def test_single_plan_mode(self):
        result = plan_route.plan_variants(self.data, 1)
        self.assertEqual(len(result["plans"]), 1)

    def test_multigenerational_rest_and_caps(self):
        data = load_fixture()
        data["options"]["experience_level"] = "experienced"
        data["options"]["members"] = [
            {"band": "36-50", "count": 2},
            {"band": "70+", "count": 2},
            {"band": "4-6", "count": 1},
        ]
        result = plan_route.plan_variants(data, 3)
        plans = {plan["key"]: plan for plan in result["plans"]}
        self.assertTrue(result["party"]["multigenerational"])

        b_plan = plans["B"]
        self.assertEqual(b_plan["summary"]["rest_protected_min"], 90)
        self.assertTrue(
            any(segment["category"] == "rest" for segment in b_plan["segments"])
        )

        a_plan = plans["A"]
        self.assertLessEqual(
            a_plan["summary"]["effective_max_walk_km"],
            a_plan["summary"]["party_max_walk_km"] * 1.10 + 1e-6,
        )
        self.assertEqual(a_plan["summary"]["total_pois"], 4)
        self.assertEqual(b_plan["summary"]["total_pois"], 3)
        self.assertEqual(plans["C"]["summary"]["total_pois"], 2)


class TestCli(unittest.TestCase):
    def test_cli_default_three_plans_from_any_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "route.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(FIXTURE_PATH),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                cwd=tmp,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "success")
            self.assertEqual(len(payload["plans"]), 3)

    def test_cli_single_plan_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "route.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--input",
                    str(FIXTURE_PATH),
                    "--plans",
                    "1",
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                cwd=tmp,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("summary", payload)
            self.assertNotIn("plans", payload)

    def test_cli_missing_file_returns_nonzero(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--input", "/tmp/not-exist-itinerary.json"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("ERROR", completed.stderr)


if __name__ == "__main__":
    unittest.main()