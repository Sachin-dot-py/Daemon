import unittest

from autonomy_engine.semantics import infer_tags_heuristic


class TestSemantics(unittest.TestCase):
    def test_infer_fwd(self):
        tags, conf = infer_tags_heuristic({"token": "FWD", "description": "Move forward", "args": []})
        self.assertIn("locomotion.forward", tags)
        self.assertGreaterEqual(conf, 0.8)

    def test_infer_grip(self):
        tags, conf = infer_tags_heuristic({"token": "GRIP", "description": "Set claw state", "args": []})
        self.assertIn("end_effector.grip", tags)
        self.assertGreaterEqual(conf, 0.8)

    def test_infer_generic(self):
        tags, conf = infer_tags_heuristic({"token": "FOO", "description": "Do thing", "args": []})
        self.assertIn("generic.action", tags)
        self.assertLessEqual(conf, 0.5)


if __name__ == "__main__":
    unittest.main()

