# DecisionLab

A local Windows desktop application for multicriteria decision support,
planned with Python 3, Tkinter and SQLite (`sqlite3`). No third-party
dependencies are required.

The domain dataclasses, business logic, SQLite repository and German Tkinter GUI
are implemented. Python 3.10 or newer with Tkinter is required.

## Project structure

| File | Responsibility |
| --- | --- |
| `main.py` | Application entry point |
| `models.py` | Decision, Alternative, Criterion and Rating domain classes |
| `services.py` | DecisionService: validation, scores, ranking and sensitivity analysis |
| `database.py` | DecisionRepository: all SQLite access |
| `ui.py` | DecisionLabApp: Tkinter views and service/repository coordination |
| `tests/test_services.py` | Business logic and sensitivity regression tests |
| `tests/test_database.py` | Repository tests using temporary databases |
| `tests/test_ui.py` | Display-independent presentation and coordination tests |
| `.gitignore` | Python, virtual environment, database, cache and build exclusions |

Calculations belong in the service layer, which must not access SQLite directly.

## Run

From the project directory, using Python 3:

```powershell
python main.py
```

This opens one main window and creates `decisionlab.db` beside `main.py`.
The start view lists saved decisions with open/delete actions. Create a decision,
edit alternatives and weighted criteria, then proceed to the rating matrix.
Continuing to ratings saves the structure to assign stable entity IDs.
Incomplete drafts and partial ratings can be saved. Evaluation requires complete,
valid data; results show the service's ranking with two decimal places.
Sensitivity analysis compares original and temporary weights and rankings without
saving scenario weights. Navigation and closing prompt for unsaved changes.
Decimal input accepts commas and points. Tables and the rating matrix have scrollbars.

## Tests

```powershell
python -m unittest discover -s tests
```

Repository tests use temporary databases and do not touch `decisionlab.db`.
Business logic tests include weighted scores, competition ranking and sensitivity analysis.

## Business logic

`DecisionService` uses only domain objects and has no GUI or database access.
`validate_for_evaluation` returns error messages, or an empty list on success.
Calculation methods raise `ValueError` for invalid input. Alternatives and criteria
need unique integer IDs to identify ratings and score keys; persistence is not required.
Weights must be finite real numbers (booleans are rejected), and their sum must
be within `1e-9` of 100. Rating values must be integers from 1 to 5.

Scores use unrounded weighted terms and `math.fsum`. Rankings return immutable
`RankingEntry` objects with `alternative_id`, `score` and `rank`. Competition ties
use `1e-12` relative and absolute tolerance against the highest score in each tie
group, with ascending alternative IDs within the group.

Sensitivity returns a typed dictionary containing `original_weights`,
`scenario_weights`, `original_scores`, `scenario_scores`, `original_ranking` and
`scenario_ranking`. Weight and score dictionaries are keyed by their entity IDs.
Temporary criteria are copies; original inputs remain unchanged.

## Persistence

`DecisionRepository()` creates the schema in `decisionlab.db` by default;
pass a file path to use another database. Every connection enables foreign keys.
`get_decision(id)` returns `DecisionDetails` containing the decision, alternatives,
criteria and ratings, or `None` if the decision is missing.

`save_decision(decision, alternatives, criteria, ratings)` atomically saves the
complete supplied state. Omitted children are removed. Existing IDs are preserved;
objects with `id=None` receive generated IDs after commit. Child `decision_id`
fields are assigned to the saved decision. Save new alternatives and criteria
first with an empty ratings list, then construct ratings using their generated
IDs and save the complete state again. Ratings must reference children included
in that save. Missing or foreign entity IDs raise `ValueError`; SQL constraint
violations raise `sqlite3.IntegrityError`. Failed saves leave database state and
generated object IDs unchanged.

`delete_decision(id)` also deletes its alternatives, criteria and ratings.
Deleting a missing decision is a no-op. Evaluation rules belong in the service
implementation; the repository can store incomplete drafts.
