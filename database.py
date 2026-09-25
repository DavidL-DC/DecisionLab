"""SQLite persistence for complete decision aggregates."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Iterator

from models import Alternative, Criterion, Decision, Rating


@dataclass
class DecisionDetails:
    """A decision and all its related entities."""

    decision: Decision
    alternatives: list[Alternative]
    criteria: list[Criterion]
    ratings: list[Rating]


class DecisionRepository:
    """Store decisions in a local database, creating its schema on construction."""

    def __init__(self, database_path: str | Path = "decisionlab.db") -> None:
        self.database_path = database_path
        self.initialize_database()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_database(self) -> None:
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alternatives (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    decision_id INTEGER NOT NULL
                        REFERENCES decisions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS criteria (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    weight REAL NOT NULL,
                    decision_id INTEGER NOT NULL
                        REFERENCES decisions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY,
                    alternative_id INTEGER NOT NULL
                        REFERENCES alternatives(id) ON DELETE CASCADE,
                    criterion_id INTEGER NOT NULL
                        REFERENCES criteria(id) ON DELETE CASCADE,
                    value INTEGER NOT NULL,
                    UNIQUE (alternative_id, criterion_id)
                );
            """)

    def get_all_decisions(self) -> list[Decision]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, name, description FROM decisions ORDER BY id"
            ).fetchall()
        return [Decision(*row) for row in rows]

    def get_decision(self, decision_id: int) -> DecisionDetails | None:
        with self._connection() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT id, name, description FROM decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            alternatives = connection.execute(
                "SELECT id, name, decision_id FROM alternatives "
                "WHERE decision_id = ? ORDER BY id", (decision_id,),
            ).fetchall()
            criteria = connection.execute(
                "SELECT id, name, weight, decision_id FROM criteria "
                "WHERE decision_id = ? ORDER BY id", (decision_id,),
            ).fetchall()
            ratings = connection.execute(
                "SELECT r.id, r.alternative_id, r.criterion_id, r.value "
                "FROM ratings r JOIN alternatives a ON a.id = r.alternative_id "
                "WHERE a.decision_id = ? ORDER BY r.id", (decision_id,),
            ).fetchall()
        return DecisionDetails(
            Decision(*row), [Alternative(*r) for r in alternatives],
            [Criterion(*r) for r in criteria], [Rating(*r) for r in ratings],
        )

    def save_decision(
        self, decision: Decision, alternatives: list[Alternative],
        criteria: list[Criterion], ratings: list[Rating],
    ) -> None:
        """Atomically replace a decision's state with the supplied collections.

        None IDs request inserts; existing IDs must belong to this decision.
        Omitted entities are deleted. IDs and child decision_id fields are
        assigned only after commit. Save new alternatives and criteria before
        constructing ratings with their generated IDs. Missing decisions raise
        ValueError; database constraint violations raise sqlite3.IntegrityError.
        """
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if decision.id is None:
                decision_id = connection.execute(
                    "INSERT INTO decisions (name, description) VALUES (?, ?)",
                    (decision.name, decision.description),
                ).lastrowid
            else:
                decision_id = decision.id
                cursor = connection.execute(
                    "UPDATE decisions SET name = ?, description = ? WHERE id = ?",
                    (decision.name, decision.description, decision_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("Decision does not exist.")

            # Capture ownership before cascading deletions remove any ratings.
            rating_ids = {row[0] for row in connection.execute(
                "SELECT r.id FROM ratings r JOIN alternatives a "
                "ON a.id = r.alternative_id WHERE a.decision_id = ?",
                (decision_id,),
            )}
            alternative_ids = self._save_children(
                connection, "alternatives", alternatives, decision_id,
            )
            criterion_ids = self._save_children(
                connection, "criteria", criteria, decision_id,
            )
            connection.execute(
                "DELETE FROM ratings WHERE alternative_id IN "
                "(SELECT id FROM alternatives WHERE decision_id = ?)",
                (decision_id,),
            )
            saved_rating_ids = [None] * len(ratings)
            # Restore explicit IDs first so new ratings cannot reuse them.
            for index, rating in sorted(
                enumerate(ratings), key=lambda item: item[1].id is None,
            ):
                if rating.id is not None and rating.id not in rating_ids:
                    raise ValueError("Rating does not belong to this decision.")
                if (rating.alternative_id not in alternative_ids
                        or rating.criterion_id not in criterion_ids):
                    raise ValueError("Rating references must belong to this decision.")
                cursor = connection.execute(
                    "INSERT INTO ratings (id, alternative_id, criterion_id, value) "
                    "VALUES (?, ?, ?, ?)",
                    (rating.id, rating.alternative_id, rating.criterion_id, rating.value),
                )
                saved_rating_ids[index] = cursor.lastrowid

        decision.id = decision_id
        for child, child_id in zip(alternatives + criteria, alternative_ids + criterion_ids):
            child.id = child_id
            child.decision_id = decision_id
        for rating, rating_id in zip(ratings, saved_rating_ids):
            rating.id = rating_id

    def _save_children(
        self, connection: sqlite3.Connection, table: str,
        children: list[Alternative] | list[Criterion], decision_id: int,
    ) -> list[int]:
        # Table and column names are internal constants, never user input.
        existing_ids = {row[0] for row in connection.execute(
            f"SELECT id FROM {table} WHERE decision_id = ?", (decision_id,),
        )}
        supplied_ids = [child.id for child in children if child.id is not None]
        if len(supplied_ids) != len(set(supplied_ids)):
            raise ValueError("Duplicate child ID in save.")
        if not set(supplied_ids) <= existing_ids:
            raise ValueError("Child does not belong to this decision.")
        # Insert before deletion so omitted IDs are not reused in this save.
        saved_ids = []
        for child in children:
            columns = "name, weight" if table == "criteria" else "name"
            values = (child.name, child.weight) if isinstance(child, Criterion) else (child.name,)
            if child.id is None:
                placeholders = ", ".join("?" for _ in values)
                cursor = connection.execute(
                    f"INSERT INTO {table} ({columns}, decision_id) "
                    f"VALUES ({placeholders}, ?)", (*values, decision_id),
                )
                saved_ids.append(cursor.lastrowid)
            else:
                assignments = ", ".join(f"{column} = ?" for column in columns.split(", "))
                connection.execute(
                    f"UPDATE {table} SET {assignments} WHERE id = ?",
                    (*values, child.id),
                )
                saved_ids.append(child.id)
        connection.executemany(
            f"DELETE FROM {table} WHERE id = ?",
            [(child_id,) for child_id in existing_ids - set(supplied_ids)],
        )
        return saved_ids

    def delete_decision(self, decision_id: int) -> None:
        """Delete a decision and its children; missing IDs are a no-op."""
        with self._connection() as connection:
            connection.execute("DELETE FROM decisions WHERE id = ?", (decision_id,))
