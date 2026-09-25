"""Business rules and laptop sensitivity regression tests."""

from copy import deepcopy
import unittest

from models import Alternative, Criterion, Rating
from services import DecisionService


class DecisionServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = DecisionService()
        self.alternatives = [Alternative(i, name, 1) for i, name in enumerate(
            ("ThinkPad", "Dell", "MacBook"), 1)]
        self.criteria = [Criterion(i, name, weight, 1) for i, (name, weight) in enumerate(
            (("Price", 40), ("Performance", 35), ("Battery", 25)), 1)]
        self.ratings = [Rating(None, a, c, value)
                        for a, values in enumerate(((4, 5, 4), (5, 4, 3), (3, 5, 5)), 1)
                        for c, value in enumerate(values, 1)]

    def validate(self):
        return self.service.validate_for_evaluation(self.alternatives, self.criteria, self.ratings)

    def sensitivity(self, criterion_id=1, new_weight=50):
        return self.service.calculate_sensitivity(
            self.alternatives, self.criteria, self.ratings, criterion_id, new_weight)

    def test_valid_evaluation(self):
        self.assertEqual(self.validate(), [])

    def test_fewer_than_two_alternatives(self):
        self.alternatives = self.alternatives[:1]
        self.assertIn("At least 2 alternatives", " ".join(self.validate()))

    def test_no_criteria(self):
        self.criteria = []
        self.assertIn("At least 1 criterion", " ".join(self.validate()))

    def test_weights_must_sum_to_100(self):
        self.criteria[0].weight = 30
        self.assertIn("sum to 100%", " ".join(self.validate()))

    def test_invalid_weights(self):
        for value in (-1, 101, "40", None, True, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.criteria[0].weight = value
                self.assertIn("finite number", " ".join(self.validate()))

    def test_weight_boundaries(self):
        for c, weight in zip(self.criteria, (100, 0, 0)):
            c.weight = weight
        self.assertEqual(self.validate(), [])

    def test_incomplete_ratings(self):
        self.ratings.pop()
        self.assertIn("exactly one rating", " ".join(self.validate()))

    def test_duplicate_ratings(self):
        self.ratings.append(deepcopy(self.ratings[0]))
        self.assertIn("exactly one rating", " ".join(self.validate()))

    def test_invalid_rating_values(self):
        for value in (0, 6, 3.0, True, "3", None, float("nan")):
            with self.subTest(value=value):
                self.ratings[0].value = value
                self.assertIn("integers from 1 to 5", " ".join(self.validate()))

    def test_unknown_rating_references(self):
        for attribute in ("alternative_id", "criterion_id"):
            with self.subTest(attribute=attribute):
                rating = deepcopy(self.ratings[0])
                setattr(rating, attribute, 999)
                self.ratings.append(rating)
                self.assertIn("reference a supplied", " ".join(self.validate()))
                self.ratings.pop()

    def test_missing_or_duplicate_entity_ids(self):
        for entities in (self.alternatives, self.criteria):
            original = entities[0].id
            for invalid_id in (None, entities[1].id, True):
                with self.subTest(invalid_id=invalid_id):
                    entities[0].id = invalid_id
                    self.assertTrue(self.validate())
            entities[0].id = original

    def test_weighted_score_regression(self):
        scores = self.service.calculate_scores(self.alternatives, self.criteria, self.ratings)
        self.assertEqual(set(scores), {1, 2, 3})
        for a, expected in ((1, 4.35), (2, 4.15), (3, 4.20)):
            self.assertAlmostEqual(scores[a], expected)

    def test_scores_do_not_mutate_inputs(self):
        before = deepcopy((self.alternatives, self.criteria, self.ratings))
        self.service.calculate_scores(self.alternatives, self.criteria, self.ratings)
        self.assertEqual((self.alternatives, self.criteria, self.ratings), before)

    def test_invalid_evaluation_cannot_be_scored(self):
        self.ratings.pop()
        with self.assertRaisesRegex(ValueError, "exactly one rating"):
            self.service.calculate_scores(self.alternatives, self.criteria, self.ratings)

    def test_descending_ranking(self):
        ranking = self.service.create_ranking({1: 2.0, 2: 5.0, 3: 3.0})
        self.assertEqual([(r.alternative_id, r.score, r.rank) for r in ranking],
                         [(2, 5.0, 1), (3, 3.0, 2), (1, 2.0, 3)])

    def test_competition_ranking_and_deterministic_ties(self):
        scores = {3: 3.0, 2: 4.0, 1: 4.0}
        ranking = self.service.create_ranking(scores)
        self.assertEqual([r.alternative_id for r in ranking], [1, 2, 3])
        self.assertEqual([r.rank for r in ranking], [1, 1, 3])
        self.assertEqual(scores, {3: 3.0, 2: 4.0, 1: 4.0})

    def test_float_noise_ties_but_distinct_scores_do_not(self):
        ranking = self.service.create_ranking({2: 0.1 + 0.2, 1: 0.3, 3: 0.299999})
        self.assertEqual([r.alternative_id for r in ranking], [1, 2, 3])
        self.assertEqual([r.rank for r in ranking], [1, 1, 3])

    def test_empty_ranking(self):
        self.assertEqual(self.service.create_ranking({}), [])

    def test_invalid_ranking_scores(self):
        for value in (float("nan"), float("inf"), "4", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.service.create_ranking({1: value})

    def test_sensitivity_regression(self):
        result = self.sensitivity()
        self.assertEqual(result["original_weights"], {1: 40, 2: 35, 3: 25})
        for c, expected in ((1, 50), (2, 29.1666667), (3, 20.8333333)):
            self.assertAlmostEqual(result["scenario_weights"][c], expected, places=6)
        self.assertAlmostEqual(sum(result["scenario_weights"].values()), 100)
        for a, expected in ((1, 4.35), (2, 4.15), (3, 4.20)):
            self.assertAlmostEqual(result["original_scores"][a], expected)
        for a, expected in ((1, 4.2916667), (2, 4.2916667), (3, 4.0)):
            self.assertAlmostEqual(result["scenario_scores"][a], expected, places=6)
        self.assertEqual([r.alternative_id for r in result["original_ranking"]], [1, 3, 2])
        self.assertEqual([r.rank for r in result["original_ranking"]], [1, 2, 3])
        self.assertEqual([r.alternative_id for r in result["scenario_ranking"]], [1, 2, 3])
        self.assertEqual([r.rank for r in result["scenario_ranking"]], [1, 1, 3])

    def test_sensitivity_does_not_mutate_inputs(self):
        before = deepcopy((self.alternatives, self.criteria, self.ratings))
        result = self.sensitivity()
        result["scenario_weights"][1] = 0
        result["original_weights"][1] = 0
        self.assertEqual((self.alternatives, self.criteria, self.ratings), before)

    def test_invalid_sensitivity_weights(self):
        before = deepcopy(self.criteria)
        for value in (-1, 101, "50", True, None, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "New weight"):
                self.sensitivity(new_weight=value)
        self.assertEqual(self.criteria, before)

    def test_sensitivity_requires_two_positive_weights(self):
        for c, weight in zip(self.criteria, (100, 0, 0)):
            c.weight = weight
        with self.assertRaisesRegex(ValueError, "at least two.*positive"):
            self.sensitivity()

    def test_unknown_sensitivity_criterion(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.sensitivity(criterion_id=999)

    def test_sensitivity_validates_original_evaluation(self):
        self.criteria[0].weight = 30
        with self.assertRaisesRegex(ValueError, "sum to 100"):
            self.sensitivity()

    def test_sensitivity_boundary_weights(self):
        for value in (0, 100):
            with self.subTest(value=value):
                result = self.sensitivity(new_weight=value)
                self.assertAlmostEqual(result["scenario_weights"][1], value)
                self.assertAlmostEqual(sum(result["scenario_weights"].values()), 100)

    def test_zero_weight_stays_zero_when_not_selected(self):
        for c, weight in zip(self.criteria, (40, 60, 0)):
            c.weight = weight
        self.assertEqual(self.sensitivity()["scenario_weights"], {1: 50, 2: 50, 3: 0})

    def test_selecting_originally_zero_weight(self):
        for c, weight in zip(self.criteria, (0, 60, 40)):
            c.weight = weight
        self.assertEqual(self.sensitivity()["scenario_weights"], {1: 50, 2: 30, 3: 20})


if __name__ == "__main__":
    unittest.main()
