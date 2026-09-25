"""Display-independent checks for presentation and application coordination."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from database import DecisionDetails, DecisionRepository
from models import Alternative, Criterion, Decision, Rating
from services import DecisionService
from ui import DecisionLabApp, display_number, german_error, parse_number, structural_errors


class PresentationTests(unittest.TestCase):
    def test_german_decimal_input_and_output(self):
        self.assertAlmostEqual(parse_number(" 29,1667 "), 29.1667)
        self.assertAlmostEqual(parse_number("29.1667"), 29.1667)
        self.assertEqual(display_number(4.2916667), "4,29")
        with self.assertRaises(ValueError):
            parse_number("keine Zahl")

    def test_structural_validation_handles_unsaved_entities_without_mutation(self):
        alternatives = [Alternative(None, "A", None), Alternative(None, "B", None)]
        criteria = [Criterion(None, "Preis", 100, None)]
        before = deepcopy((alternatives, criteria))
        self.assertEqual(structural_errors(DecisionService(), alternatives, criteria), [])
        self.assertEqual((alternatives, criteria), before)

    def test_structural_errors_come_from_service(self):
        service = Mock()
        service.validate_for_evaluation.return_value = ["Fehler"]
        self.assertEqual(structural_errors(service, [], []), ["Fehler"])
        service.validate_for_evaluation.assert_called_once_with([], [], [])

    def test_structural_validation_rejects_incomplete_draft(self):
        errors = structural_errors(DecisionService(), [], [Criterion(None, "Preis", 50, None)])
        self.assertTrue(any("At least 2" in e for e in errors))
        self.assertTrue(any("sum to 100" in e for e in errors))

    def test_service_errors_are_translated(self):
        self.assertIn("zwei", german_error("At least 2 alternatives are required."))
        self.assertIn("100 %", german_error("Criterion weights must sum to 100%."))
        self.assertIn("genau einmal", german_error("Alternative 'A' must have exactly one rating for criterion 'C'."))
        self.assertIn("prüfen", german_error("Unknown internal diagnostic"))


class ApplicationCoordinationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = DecisionLabApp.__new__(DecisionLabApp)
        self.app.repository = DecisionRepository(Path(directory.name) / "test.db")
        self.app.service = DecisionService()
        self.app.details = DecisionDetails(Decision(None, "Test", ""),
            [Alternative(None, "A", None), Alternative(None, "B", None)],
            [Criterion(None, "Preis", 100, None)], [])
        self.app.saved = None
        self.app._error = Mock()

    def test_draft_then_partial_ratings_can_be_saved_and_reopened(self):
        self.assertTrue(self.app._persist(False))
        d = self.app.details
        self.app.rating_variables = {
            (d.alternatives[0].id, d.criteria[0].id): Mock(get=lambda: "4"),
            (d.alternatives[1].id, d.criteria[0].id): Mock(get=lambda: ""),
        }
        self.assertTrue(self.app._capture_ratings())
        self.assertTrue(self.app._persist(False))
        loaded = self.app.repository.get_decision(d.decision.id)
        self.assertEqual(len(loaded.ratings), 1)
        self.assertEqual(loaded.ratings[0].value, 4)
        self.assertEqual(self.app.details, self.app.saved)

    def test_invalid_rating_is_rejected_without_changing_state(self):
        self.app._persist(False)
        d = self.app.details
        for value in ("6", "Text", "2.5"):
            with self.subTest(value=value):
                self.app.rating_variables = {(d.alternatives[0].id, d.criteria[0].id): Mock(get=lambda: value)}
                self.assertFalse(self.app._capture_ratings())
                self.assertEqual(d.ratings, [])

    def test_incomplete_ratings_do_not_open_results(self):
        self.app._persist(False)
        self.app.rating_variables = {}
        self.app.show_results = Mock()
        self.app._evaluate()
        self.app.show_results.assert_not_called()
        self.app._error.assert_called_once()

    def test_failed_save_does_not_update_saved_snapshot(self):
        self.app._persist(False)
        before = deepcopy(self.app.saved)
        self.app.details.decision.name = "Änderung"
        with patch.object(self.app.repository, "save_decision", side_effect=ValueError):
            self.assertFalse(self.app._persist(False))
        self.assertEqual(self.app.saved, before)


if __name__ == "__main__":
    unittest.main()
