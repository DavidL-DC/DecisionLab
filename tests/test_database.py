"""Repository integration tests, isolated in temporary SQLite databases."""

from contextlib import closing
from dataclasses import is_dataclass
from pathlib import Path
import sqlite3
import tempfile
import unittest

from database import DecisionRepository
from models import Alternative, Criterion, Decision, Rating


class DecisionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "test.db"
        self.repository = DecisionRepository(self.path)

    def create_decision(self):
        decision = Decision(None, "Laptop", "Choose a laptop")
        alternatives = [Alternative(None, name, None) for name in ("A", "B")]
        criteria = [Criterion(None, "Price", 60.0, None), Criterion(None, "Speed", 40.0, None)]
        self.repository.save_decision(decision, alternatives, criteria, [])
        ratings = [Rating(None, a.id, c.id, 3) for a in alternatives for c in criteria]
        self.repository.save_decision(decision, alternatives, criteria, ratings)
        return decision, alternatives, criteria, ratings

    def test_models_are_dataclasses_with_unpersisted_ids(self):
        for entity in (Decision(None, "D", ""), Alternative(None, "A", None),
                       Criterion(None, "C", 100.0, None), Rating(None, None, None, 1)):
            self.assertTrue(is_dataclass(entity))
            self.assertIsNone(entity.id)

    def test_initialization_is_automatic_and_idempotent(self):
        self.assertTrue(self.path.exists())
        self.repository.initialize_database()
        self.assertEqual(self.repository.get_all_decisions(), [])
        self.assertIsNone(self.repository.get_decision(999))
        self.repository.delete_decision(999)

    def test_round_trip_and_reopen(self):
        decision, alternatives, criteria, ratings = self.create_decision()
        repository = DecisionRepository(self.path)
        details = repository.get_decision(decision.id)
        self.assertEqual(details.decision, decision)
        self.assertEqual(details.alternatives, alternatives)
        self.assertEqual(details.criteria, criteria)
        self.assertEqual(details.ratings, ratings)
        self.assertEqual(repository.get_all_decisions(), [decision])
        self.assertTrue(all(a.decision_id == decision.id for a in alternatives))
        self.assertTrue(all(c.decision_id == decision.id for c in criteria))

    def test_update_preserves_ids_and_removes_omitted_entities(self):
        decision, alternatives, criteria, ratings = self.create_decision()
        original_id = alternatives[0].id
        decision.name = "Updated"
        alternatives[0].name = "Renamed"
        criteria[0].weight = 100.0
        ratings[0].value = 5
        new_alternative = Alternative(None, "C", None)
        self.repository.save_decision(
            decision, [alternatives[0], new_alternative], criteria[:1], ratings[:1],
        )
        details = self.repository.get_decision(decision.id)
        self.assertEqual(details.decision.name, "Updated")
        self.assertEqual(details.alternatives, [alternatives[0], new_alternative])
        self.assertEqual(details.alternatives[0].id, original_id)
        self.assertEqual(details.criteria, criteria[:1])
        self.assertEqual(details.ratings, ratings[:1])

    def test_new_rating_before_existing_rating(self):
        decision, alternatives, criteria, ratings = self.create_decision()
        new_rating = Rating(None, alternatives[0].id, criteria[0].id, 5)
        self.repository.save_decision(decision, alternatives, criteria, [new_rating, ratings[1]])
        details = self.repository.get_decision(decision.id)
        self.assertCountEqual(details.ratings, [new_rating, ratings[1]])

    def test_duplicate_ratings_roll_back_entire_update_and_object_ids(self):
        decision, alternatives, criteria, ratings = self.create_decision()
        before = self.repository.get_decision(decision.id)
        decision.name = "Must roll back"
        new_alternative = Alternative(None, "New", None)
        duplicate = Rating(None, alternatives[0].id, criteria[0].id, 4)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.save_decision(
                decision, alternatives + [new_alternative], criteria, ratings + [duplicate],
            )
        self.assertEqual(self.repository.get_decision(decision.id), before)
        self.assertIsNone(new_alternative.id)
        self.assertIsNone(new_alternative.decision_id)
        self.assertIsNone(duplicate.id)

    def test_failed_creation_does_not_publish_ids_or_partial_rows(self):
        decision = Decision(None, "New", "")
        alternative = Alternative(None, "A", None)
        criterion = Criterion(None, "C", 100.0, None)
        with self.assertRaises(ValueError):
            self.repository.save_decision(
                decision, [alternative], [criterion], [Rating(None, 999, 999, 3)],
            )
        self.assertEqual(self.repository.get_all_decisions(), [])
        self.assertIsNone(decision.id)
        self.assertIsNone(alternative.id)
        self.assertIsNone(criterion.id)

    def test_other_decisions_cannot_be_modified_through_child_ids(self):
        first, alternatives, criteria, ratings = self.create_decision()
        second, other_alternatives, other_criteria, other_ratings = self.create_decision()
        before = self.repository.get_decision(second.id)
        with self.assertRaises(ValueError):
            self.repository.save_decision(first, other_alternatives, criteria, [])
        with self.assertRaises(ValueError):
            self.repository.save_decision(
                first, alternatives, criteria,
                [Rating(None, alternatives[0].id, other_criteria[0].id, 2)],
            )
        with self.assertRaises(ValueError):
            self.repository.save_decision(first, alternatives, criteria, other_ratings)
        self.assertEqual(self.repository.get_decision(second.id), before)
        self.assertEqual(self.repository.get_decision(first.id).ratings, ratings)

    def test_missing_decision_update_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repository.save_decision(Decision(999, "Missing", ""), [], [], [])
        self.assertEqual(self.repository.get_all_decisions(), [])

    def test_delete_cascades_and_preserves_other_decisions(self):
        first, *_ = self.create_decision()
        second, *_ = self.create_decision()
        before = self.repository.get_decision(second.id)
        self.repository.delete_decision(first.id)
        self.assertIsNone(self.repository.get_decision(first.id))
        self.assertEqual(self.repository.get_decision(second.id), before)
        self.repository.delete_decision(second.id)
        with closing(sqlite3.connect(self.path)) as connection:
            for table in ("decisions", "alternatives", "criteria", "ratings"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_every_connection_enforces_foreign_keys(self):
        for _ in range(2):
            with self.repository._connection() as connection:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "INSERT INTO alternatives (name, decision_id) VALUES ('Orphan', 999)"
                    )

    def test_empty_draft_and_clearing_children(self):
        decision, *_ = self.create_decision()
        self.repository.save_decision(decision, [], [], [])
        details = self.repository.get_decision(decision.id)
        self.assertEqual((details.alternatives, details.criteria, details.ratings), ([], [], []))


if __name__ == "__main__":
    unittest.main()
