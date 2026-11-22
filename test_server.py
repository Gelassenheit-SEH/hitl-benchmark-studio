import unittest
from unittest.mock import patch

import server


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.studio = server.Studio()

    def start(self, preset="balanced"):
        return self.studio.start(preset)

    def review(self, batch, sample, action, **fields):
        return self.studio.review({
            "batch_id": batch["id"], "sample_id": sample["id"],
            "version": len(sample["ai_preannotation_versions"]),
            "action": action, **fields,
        })

    def test_allocates_both_presets_and_counts_separately(self):
        for name, expected in [
            ("balanced", {"C1": 1, "C2": 1, "C3": 1, "C4": 1}),
            ("quantitative", {"C1": 1, "C2": 0, "C3": 1, "C4": 2}),
        ]:
            batch = self.start(name)
            self.assertEqual(expected, batch["planned"])
            self.assertEqual(expected, batch["generated"])
            self.assertEqual(0, sum(batch["released"].values()))
            self.assertEqual("C4", batch["samples"][0]["category"])
            self.assertCountEqual(["Physics", "Physics", "Mathematics", "Mathematics"],
                                  [sample["subject"] for sample in batch["samples"]])
        self.assertEqual(
            {"C1": 2, "C2": 1, "C3": 1, "C4": 1},
            server.allocate_controlled_error_counts(5, {f"C{i}": 25 for i in range(1, 5)}),
        )

    def test_guided_review_changes_the_right_artifact_and_exports(self):
        batch = self.start()
        original = batch["samples"][0]
        failed = self.review(batch, original, "reinject", note="The candidate also changes the speed.")
        revised_candidate = failed["samples"][0]
        self.assertEqual("C4", revised_candidate["category"])
        self.assertEqual(2, len(revised_candidate["candidates"]))
        self.assertEqual(2, len(revised_candidate["ai_preannotation_versions"]))
        self.assertNotEqual(original["candidates"][0]["text"], revised_candidate["candidates"][1]["text"])

        revision = self.review(failed, revised_candidate, "revise", instructions={
            "minimal_repair": "Use the conversion in the reference.",
            "error_explanation": "   ",
        })
        revised = revision["samples"][0]
        self.assertEqual(revised_candidate["candidates"], revised["candidates"])
        before = revised_candidate["ai_preannotation"]["suggested_errors"][0]
        after = revised["ai_preannotation"]["suggested_errors"][0]
        self.assertEqual({"minimal_repair"}, {key for key in before if before[key] != after[key]})
        self.assertEqual([], self.studio.export())
        released = self.review(revision, revised, "release")
        result = self.studio.export()[0]
        self.assertEqual(1, released["released"]["C4"])
        self.assertEqual("human", result["release"]["actor"])
        self.assertEqual("reviewed", result["release"]["decision"])
        self.assertNotIn("checks", result["release"])
        self.assertNotIn("evidence", result["release"])
        self.assertIn("E2", result["reference_evidence"])
        self.assertEqual(2, result["candidate_version"])
        self.assertEqual(3, result["annotation_version"])
        self.assertEqual(["reinject", "revise", "release"], [event["action"] for event in result["review_history"]])

    def test_rejects_stale_update(self):
        batch = self.start()
        sample = batch["samples"][0]
        self.assertEqual([], self.studio.export())
        self.review(batch, sample, "reinject", note="Additional error")
        with self.assertRaises(server.ApiError) as stale:
            self.review(batch, sample, "release")
        self.assertEqual(409, stale.exception.status)

    def test_invalid_model_reply_does_not_change_candidate_or_history(self):
        batch = self.start()
        with patch("server.inject", return_value={"candidate_output": "invalid"}):
            with self.assertRaises(server.ApiError):
                self.review(batch, batch["samples"][0], "reinject", note="Review again")
        self.assertEqual(batch, self.studio.snapshot()["batch"])

    def test_override_preserves_candidate_and_records_human_judgment(self):
        batch = self.start()
        sample = batch["samples"][0]
        edited = self.review(batch, sample, "override", judgment="insufficient_evidence")
        revised = edited["samples"][0]
        self.assertEqual(sample["candidates"], revised["candidates"])
        self.assertEqual("insufficient_evidence", revised["ai_preannotation"]["suggested_judgment"])
        with self.assertRaises(server.ApiError):
            self.review(edited, revised, "release")
        rejected = self.review(edited, revised, "reject", note="Missing context")
        self.assertEqual("rejected", rejected["samples"][0]["status"])
        self.assertEqual([], self.studio.export())

    def test_partial_override_keeps_blank_fields_without_a_reason(self):
        batch = self.start()
        sample = batch["samples"][0]
        updated = self.review(batch, sample, "override", fields={
            "minimal_repair": "Corrected repair", "scientific_constraint": "   ", "error_category": "",
        })["samples"][0]
        previous = sample["ai_preannotation"]["suggested_errors"][0]
        current = updated["ai_preannotation"]["suggested_errors"][0]
        self.assertEqual({**previous, "minimal_repair": "Corrected repair"}, current)
        self.assertEqual(sample["candidates"], updated["candidates"])
        self.assertNotIn("note", updated["review_history"][-1])

    def test_reset_invalidates_previous_batch(self):
        old = self.start()
        self.studio.reset()
        fresh = self.start()
        self.assertNotEqual(old["id"], fresh["id"])
        with self.assertRaises(server.ApiError):
            self.review(old, old["samples"][0], "reinject", note="Stale action")
