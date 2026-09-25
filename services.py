"""Pure business operations without GUI or database access."""

from collections import Counter
from dataclasses import dataclass, replace
from math import fsum, isclose, isfinite
from numbers import Real
from typing import TypedDict

from models import Alternative, Criterion, Rating


@dataclass(frozen=True)
class RankingEntry:
    alternative_id: int
    score: float
    rank: int


class SensitivityResult(TypedDict):
    original_weights: dict[int, float]
    scenario_weights: dict[int, float]
    original_scores: dict[int, float]
    scenario_scores: dict[int, float]
    original_ranking: list[RankingEntry]
    scenario_ranking: list[RankingEntry]


def _valid_weight(value: object) -> bool:
    return (isinstance(value, Real) and not isinstance(value, bool)
            and 0 <= value <= 100 and isfinite(value))


class DecisionService:
    """Inputs are never modified; invalid calculations raise ValueError.

    Alternatives and criteria need unique integer IDs, but need not be persisted.
    """

    def validate_for_evaluation(
        self, alternatives: list[Alternative], criteria: list[Criterion], ratings: list[Rating],
    ) -> list[str]:
        errors = []
        if len(alternatives) < 2:
            errors.append("At least 2 alternatives are required.")
        if not criteria:
            errors.append("At least 1 criterion is required.")
        for label, entities in (("Alternative", alternatives), ("Criterion", criteria)):
            ids = [entity.id for entity in entities]
            if any(type(entity_id) is not int for entity_id in ids):
                errors.append(f"{label} IDs must be integers, not None.")
            elif len(set(ids)) != len(ids):
                errors.append(f"{label} IDs must be unique.")
        for criterion in criteria:
            if not _valid_weight(criterion.weight):
                errors.append(f"Weight for '{criterion.name}' must be a finite number between 0 and 100.")
        if criteria and all(_valid_weight(c.weight) for c in criteria):
            if not isclose(fsum(c.weight for c in criteria), 100, rel_tol=0, abs_tol=1e-9):
                errors.append("Criterion weights must sum to 100%.")
        alternative_ids = {a.id for a in alternatives if type(a.id) is int}
        criterion_ids = {c.id for c in criteria if type(c.id) is int}
        counts = Counter()
        for rating in ratings:
            if (type(rating.alternative_id) is not int or type(rating.criterion_id) is not int
                    or rating.alternative_id not in alternative_ids
                    or rating.criterion_id not in criterion_ids):
                errors.append("Every rating must reference a supplied alternative and criterion.")
            else:
                counts[rating.alternative_id, rating.criterion_id] += 1
            if type(rating.value) is not int or not 1 <= rating.value <= 5:
                errors.append("Rating values must be integers from 1 to 5 inclusive.")
        for alternative in alternatives:
            for criterion in criteria:
                if (type(alternative.id) is int and type(criterion.id) is int
                        and counts[alternative.id, criterion.id] != 1):
                    errors.append(f"Alternative '{alternative.name}' must have exactly one rating "
                                  f"for criterion '{criterion.name}'.")
        return errors

    def calculate_scores(
        self, alternatives: list[Alternative], criteria: list[Criterion], ratings: list[Rating],
    ) -> dict[int, float]:
        errors = self.validate_for_evaluation(alternatives, criteria, ratings)
        if errors:
            raise ValueError(" ".join(errors))
        values = {(r.alternative_id, r.criterion_id): r.value for r in ratings}
        return {a.id: fsum(values[a.id, c.id] * (c.weight / 100) for c in criteria)
                for a in alternatives}

    def create_ranking(self, scores: dict[int, float]) -> list[RankingEntry]:
        """Competition ties use 1e-12 relative/absolute tolerance and ID order.

        Compare against the highest score in each tie group; retain raw scores.
        """
        for alternative_id, score in scores.items():
            if type(alternative_id) is not int:
                raise ValueError("Alternative IDs must be integers.")
            if (not isinstance(score, Real) or isinstance(score, bool) or not isfinite(score)):
                raise ValueError("Scores must be finite numbers.")
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        result = []
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and isclose(
                ordered[end][1], ordered[start][1], rel_tol=1e-12, abs_tol=1e-12,
            ):
                end += 1
            result.extend(RankingEntry(a, score, start + 1)
                          for a, score in sorted(ordered[start:end]))
            start = end
        return result

    def calculate_sensitivity(
        self, alternatives: list[Alternative], criteria: list[Criterion], ratings: list[Rating],
        criterion_id: int, new_weight: float,
    ) -> SensitivityResult:
        """Evaluate temporary proportional weights using copies of criteria."""
        original_scores = self.calculate_scores(alternatives, criteria, ratings)
        if not _valid_weight(new_weight):
            raise ValueError("New weight must be a finite number between 0 and 100 inclusive.")
        if type(criterion_id) is not int or criterion_id not in {c.id for c in criteria}:
            raise ValueError("Selected criterion does not exist.")
        if sum(c.weight > 0 for c in criteria) < 2:
            raise ValueError("Sensitivity analysis requires at least two criteria with positive "
                             "original weights; otherwise proportional redistribution may be impossible.")
        remaining = fsum(c.weight for c in criteria if c.id != criterion_id)
        if remaining <= 0:
            raise ValueError("Proportional redistribution is impossible: other weights sum to zero.")
        scenario = [replace(c, weight=(new_weight if c.id == criterion_id else
                                      (c.weight / remaining) * (100 - new_weight))) for c in criteria]
        scenario_scores = self.calculate_scores(alternatives, scenario, ratings)
        return SensitivityResult(
            original_weights={c.id: c.weight for c in criteria},
            scenario_weights={c.id: c.weight for c in scenario},
            original_scores=original_scores, scenario_scores=scenario_scores,
            original_ranking=self.create_ranking(original_scores),
            scenario_ranking=self.create_ranking(scenario_scores),
        )
