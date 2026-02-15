import unittest

from autonomy_engine.taskspec import TaskSpec


class TestTaskSpec(unittest.TestCase):
    def test_apply_patch_policy_params_numeric_only(self):
        spec = TaskSpec()
        applied = spec.apply_patch({"policy_params": {"default_speed": 0.8, "x": "nope", "y": True}})
        self.assertIn("policy_params.default_speed", applied)
        self.assertNotIn("policy_params.x", applied)
        self.assertNotIn("policy_params.y", applied)
        self.assertAlmostEqual(spec.policy_params["default_speed"], 0.8)

    def test_apply_patch_hard_limit(self):
        spec = TaskSpec()
        patch = {"policy_params": {f"k{i}": float(i) for i in range(40)}}
        applied = spec.apply_patch(patch)
        self.assertEqual(applied, [])


if __name__ == "__main__":
    unittest.main()

