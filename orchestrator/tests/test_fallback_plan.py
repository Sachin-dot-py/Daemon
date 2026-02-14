import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import NodeInfo, Orchestrator, fallback_plan


class FallbackPlannerTests(unittest.TestCase):
    def test_square_macro_expands_to_four_segments(self):
        plan = fallback_plan("square")["plan"]
        run_steps = [step for step in plan if step.get("type") == "RUN"]
        self.assertEqual(len(run_steps), 8)
        self.assertEqual(run_steps[0]["token"], "FWD")
        self.assertEqual(run_steps[0]["duration_ms"], 1200)
        self.assertEqual(run_steps[1]["token"], "TURN")
        self.assertEqual(run_steps[1]["args"], [90])
        self.assertEqual(plan[-1]["type"], "STOP")

    def test_left_square_uses_negative_turn(self):
        plan = fallback_plan("left square")["plan"]
        turn_steps = [step for step in plan if step.get("token") == "TURN"]
        self.assertTrue(turn_steps)
        self.assertTrue(all(step["args"] == [-90] for step in turn_steps))

    def test_straight_line_macro(self):
        plan = fallback_plan("straight line")["plan"]
        self.assertEqual(
            plan,
            [
                {"type": "RUN", "target": "base", "token": "FWD", "args": [0.6], "duration_ms": 2000},
                {"type": "STOP"},
            ],
        )

    def test_triangle_macro_expands_to_three_segments(self):
        plan = fallback_plan("triangle")["plan"]
        run_steps = [step for step in plan if step.get("type") == "RUN"]
        self.assertEqual(len(run_steps), 6)
        self.assertEqual(sum(1 for step in run_steps if step.get("token") == "FWD"), 3)
        turn_steps = [step for step in plan if step.get("token") == "TURN"]
        self.assertEqual(len(turn_steps), 3)
        self.assertTrue(all(step["args"] == [120] for step in turn_steps))
        self.assertEqual(plan[-1]["type"], "STOP")


class TokenCollisionTests(unittest.TestCase):
    def test_ambiguous_token_requires_target(self):
        base = NodeInfo(alias="base", host="127.0.0.1", port=7777)
        arm = NodeInfo(alias="arm", host="127.0.0.1", port=7778)
        base.manifest = {"commands": [{"token": "SET"}], "device": {"name": "base", "node_id": "base-1"}}
        arm.manifest = {"commands": [{"token": "SET"}], "device": {"name": "arm", "node_id": "arm-1"}}
        base.node_name = "base"
        arm.node_name = "arm"

        orchestrator = Orchestrator(nodes=[base, arm])
        orchestrator._build_catalogs()

        with self.assertRaisesRegex(RuntimeError, "Ambiguous token 'SET'"):
            orchestrator.resolve_node(None, "SET")
        self.assertIs(orchestrator.resolve_node("base", "SET"), base)
        self.assertIs(orchestrator.resolve_node("arm", "SET"), arm)


if __name__ == "__main__":
    unittest.main()
