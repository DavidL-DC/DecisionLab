"""Domain entities for DecisionLab."""

from dataclasses import dataclass


@dataclass
class Decision:
    """A decision with a name and optional description."""

    id: int | None
    name: str
    description: str


@dataclass
class Alternative:
    """An alternative belonging to a decision."""

    id: int | None
    name: str
    decision_id: int | None


@dataclass
class Criterion:
    """A weighted evaluation criterion belonging to a decision."""

    id: int | None
    name: str
    weight: float
    decision_id: int | None


@dataclass
class Rating:
    """An alternative's rating for a criterion."""

    id: int | None
    alternative_id: int | None
    criterion_id: int | None
    value: int
