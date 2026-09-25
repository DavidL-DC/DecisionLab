"""German Tkinter views coordinating domain services and persistence."""

from copy import deepcopy
from dataclasses import replace
from sqlite3 import Error as DatabaseError
import tkinter as tk
from tkinter import messagebox, ttk

from database import DecisionDetails, DecisionRepository
from models import Alternative, Criterion, Decision, Rating
from services import DecisionService


def german_error(message: str) -> str:
    """Translate service diagnostics at the presentation boundary."""
    translations = {
        "At least 2 alternatives": "Mindestens zwei Alternativen sind erforderlich.",
        "At least 1 criterion": "Mindestens ein Kriterium ist erforderlich.",
        "Criterion weights must sum": "Die Summe der Kriteriengewichte muss 100 % betragen.",
        "Weight for": "Jedes Kriteriengewicht muss eine endliche Zahl zwischen 0 und 100 sein.",
        "Rating values": "Bewertungen müssen ganze Zahlen von 1 bis 5 sein.",
        "Every rating": "Eine Bewertung verweist auf eine nicht vorhandene Alternative oder ein Kriterium.",
        "New weight": "Das neue Gewicht muss eine endliche Zahl zwischen 0 und 100 sein.",
        "Selected criterion": "Bitte wählen Sie ein vorhandenes Kriterium aus.",
        "Sensitivity analysis requires": "Für die Sensitivitätsanalyse müssen mindestens zwei ursprüngliche Kriteriengewichte größer als 0 sein.",
        "Proportional redistribution": "Die übrigen Gewichte können nicht proportional verteilt werden, da ihre Summe 0 ist.",
    }
    if "must have exactly one rating" in message:
        return "Bitte bewerten Sie jede Alternative für jedes Kriterium genau einmal."
    for prefix, translation in translations.items():
        if message.startswith(prefix):
            return translation
    return "Die Daten sind nicht gültig. Bitte prüfen Sie Alternativen, Kriterien und Bewertungen."


def structural_errors(service, alternatives, criteria):
    """Ask the service about structure using independent, complete probe ratings."""
    probe_alternatives = [replace(a, id=i) for i, a in enumerate(alternatives, 1)]
    probe_criteria = [replace(c, id=i) for i, c in enumerate(criteria, 1)]
    probe_ratings = [Rating(None, a.id, c.id, 1)
                     for a in probe_alternatives for c in probe_criteria]
    return service.validate_for_evaluation(probe_alternatives, probe_criteria, probe_ratings)


def parse_number(text: str) -> float:
    """Accept German decimal commas as well as decimal points."""
    return float(text.strip().replace(",", "."))


def display_number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


class DecisionLabApp:
    def __init__(self, root: tk.Tk, service: DecisionService, repository: DecisionRepository):
        self.root = root
        self.service = service
        self.repository = repository
        self.details = None
        self.saved = None
        self.view = "start"
        root.title("DecisionLab")
        root.geometry("1000x720")
        root.minsize(760, 520)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self.shell = ttk.Frame(root, padding=16)
        self.shell.pack(fill="both", expand=True)
        self.show_start()

    def _page(self, title, view):
        self.view = view
        for child in self.shell.winfo_children():
            child.destroy()
        ttk.Label(self.shell, text=title, font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 12))
        self.body = ttk.Frame(self.shell)
        self.body.pack(fill="both", expand=True)
        self.actions = ttk.Frame(self.shell)
        self.actions.pack(fill="x", pady=(12, 0))

    def _button(self, label, command):
        ttk.Button(self.actions, text=label, command=command).pack(side="left", padx=(0, 8))

    def _error(self, text, parent=None):
        messagebox.showerror("Eingabe prüfen", text, parent=parent or self.root)

    def _errors(self, errors):
        self._error("\n".join(dict.fromkeys(german_error(e) for e in errors)))

    def _scroll_area(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(frame, highlightthickness=0)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        content = ttk.Frame(canvas, padding=4)
        canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        return content

    def _table(self, parent, headings, rows, height=8):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=6)
        tree = ttk.Treeview(frame, columns=list(range(len(headings))), show="headings", height=height)
        for i, heading in enumerate(headings):
            tree.heading(i, text=heading)
            tree.column(i, width=160, minwidth=80)
        for index, row in enumerate(rows):
            tree.insert("", "end", iid=str(index), values=row)
        tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=bar.set, xscrollcommand=horizontal.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def _form(self, title, fields, submit_label, submit):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        variables = []
        entries = []
        for row, (label, initial) in enumerate(fields):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=6)
            variable = tk.StringVar(value=initial)
            entry = ttk.Entry(panel, textvariable=variable, width=44)
            entry.grid(row=row, column=1, padx=(12, 0), pady=6)
            variables.append(variable)
            entries.append(entry)

        def accept():
            if submit([v.get() for v in variables], dialog):
                dialog.destroy()

        controls = ttk.Frame(panel)
        controls.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(controls, text="Abbrechen", command=dialog.destroy).pack(side="left", padx=8)
        ttk.Button(controls, text=submit_label, command=accept).pack(side="left")
        dialog.bind("<Return>", lambda event: accept())
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.grab_set()
        entries[0].focus_set()

    def show_start(self):
        try:
            decisions = self.repository.get_all_decisions()
        except (DatabaseError, OSError):
            self._error("Die Entscheidungen konnten nicht geladen werden. Bitte prüfen Sie den Zugriff auf die Datenbank.")
            return
        self.details = self.saved = None
        self._page("DecisionLab", "start")
        content = self._scroll_area(self.body)
        if not decisions:
            ttk.Label(content, text="Noch keine Entscheidungen vorhanden.").grid(pady=12)
        for row, decision in enumerate(decisions):
            ttk.Label(content, text=decision.name, width=55, wraplength=480).grid(row=row, column=0, sticky="w", pady=8)
            ttk.Button(content, text="Öffnen", command=lambda d=decision: self._open(d.id)).grid(row=row, column=1, padx=8)
            ttk.Button(content, text="Löschen", command=lambda d=decision: self._delete(d)).grid(row=row, column=2)
        self._button("Neue Entscheidung", self._new)

    def _new(self):
        def submit(values, dialog):
            name, description = values
            if not name.strip():
                self._error("Bitte geben Sie einen Namen ein.", dialog)
                return False
            self.details = DecisionDetails(Decision(None, name.strip(), description.strip()), [], [], [])
            self.saved = None
            self.show_editor()
            return True
        self._form("Neue Entscheidung", [("Name", ""), ("Beschreibung (optional)", "")], "Erstellen", submit)

    def _open(self, decision_id):
        try:
            details = self.repository.get_decision(decision_id)
        except (DatabaseError, OSError):
            self._error("Die Entscheidung konnte nicht geladen werden.")
            return
        if details is None:
            self._error("Diese Entscheidung ist nicht mehr vorhanden.")
            self.show_start()
            return
        self.details = details
        self.saved = deepcopy(details)
        self.show_editor()

    def _delete(self, decision):
        if not messagebox.askyesno("Entscheidung löschen", f'„{decision.name}“ mit allen zugehörigen Daten löschen?', parent=self.root):
            return
        try:
            self.repository.delete_decision(decision.id)
        except (DatabaseError, OSError):
            self._error("Die Entscheidung konnte nicht gelöscht werden.")
            return
        self.show_start()

    def _capture_editor(self):
        self.details.decision.name = self.name.get().strip()
        self.details.decision.description = self.description.get("1.0", "end-1c")

    def show_editor(self):
        d = self.details
        self._page("Entscheidung bearbeiten", "editor")
        ttk.Label(self.body, text="Name").pack(anchor="w")
        self.name = tk.StringVar(value=d.decision.name)
        ttk.Entry(self.body, textvariable=self.name).pack(fill="x", pady=(2, 8))
        ttk.Label(self.body, text="Beschreibung (optional)").pack(anchor="w")
        self.description = tk.Text(self.body, height=3, wrap="word")
        self.description.insert("1.0", d.decision.description)
        self.description.pack(fill="x", pady=(2, 8))
        columns = ttk.Frame(self.body)
        columns.pack(fill="both", expand=True)
        for is_criterion in (False, True):
            group = ttk.LabelFrame(columns, text="Kriterien" if is_criterion else "Alternativen", padding=8)
            group.pack(side="left", fill="both", expand=True, padx=4)
            entities = d.criteria if is_criterion else d.alternatives
            rows = [(c.name, display_number(c.weight)) for c in entities] if is_criterion else [(a.name,) for a in entities]
            tree = self._table(group, ("Name", "Gewicht (%)") if is_criterion else ("Name",), rows)
            controls = ttk.Frame(group)
            controls.pack(fill="x")
            for label, action in (("Hinzufügen", "add"), ("Bearbeiten", "edit"), ("Löschen", "delete")):
                ttk.Button(controls, text=label, command=lambda k=is_criterion, t=tree, a=action: self._edit_entity(k, t, a)).pack(side="left", padx=2)
        ttk.Label(self.body, text=f"Summe der Kriteriengewichte: {display_number(sum(c.weight for c in d.criteria))} %").pack(anchor="w", pady=8)
        self._button("Zurück", self._home)
        self._button("Speichern", self._save_editor)
        self._button("Weiter zur Bewertung", self._to_ratings)

    def _edit_entity(self, is_criterion, tree, action):
        self._capture_editor()
        entities = self.details.criteria if is_criterion else self.details.alternatives
        index = None
        if action != "add":
            selection = tree.selection()
            if not selection:
                self._error("Bitte wählen Sie zuerst einen Eintrag aus.")
                return
            index = int(selection[0])
        entity = entities[index] if index is not None else None
        if action == "delete":
            if not messagebox.askyesno("Eintrag löschen", f'„{entity.name}“ und zugehörige Bewertungen entfernen?', parent=self.root):
                return
            entities.pop(index)
            self.details.ratings = [r for r in self.details.ratings if
                                   (r.criterion_id if is_criterion else r.alternative_id) != entity.id]
            self.show_editor()
            return
        fields = [("Name", entity.name if entity else "")]
        if is_criterion:
            fields.append(("Gewicht (%)", str(entity.weight) if entity else "0"))

        def submit(values, dialog):
            name = values[0].strip()
            if not name:
                self._error("Bitte geben Sie einen Namen ein.", dialog)
                return False
            if is_criterion:
                try:
                    weight = parse_number(values[1])
                except ValueError:
                    self._error("Bitte geben Sie ein numerisches Gewicht ein.", dialog)
                    return False
                # Ask the existing validator about this field; draft totals may be incomplete.
                errors = self.service.validate_for_evaluation([], [Criterion(1, name, weight, None)], [])
                weight_errors = [e for e in errors if e.startswith("Weight for")]
                if weight_errors:
                    self._error(german_error(weight_errors[0]), dialog)
                    return False
                updated = Criterion(entity.id if entity else None, name, weight, self.details.decision.id)
            else:
                updated = Alternative(entity.id if entity else None, name, self.details.decision.id)
            if index is None:
                entities.append(updated)
            else:
                entities[index] = updated
            self.show_editor()
            return True
        self._form("Kriterium" if is_criterion else "Alternative", fields, "Übernehmen", submit)

    def _persist(self, notify=True):
        d = self.details
        try:
            self.repository.save_decision(d.decision, d.alternatives, d.criteria, d.ratings)
        except (DatabaseError, OSError, ValueError):
            self._error("Speichern fehlgeschlagen. Bitte prüfen Sie den Datenbankzugriff und öffnen Sie die Entscheidung gegebenenfalls erneut.")
            return False
        self.saved = deepcopy(d)
        if notify:
            messagebox.showinfo("Gespeichert", "Die Entscheidung wurde gespeichert.", parent=self.root)
        return True

    def _save_editor(self, notify=True):
        self._capture_editor()
        if not self.details.decision.name:
            self._error("Bitte geben Sie einen Namen für die Entscheidung ein.")
            return False
        return self._persist(notify)

    def _to_ratings(self):
        self._capture_editor()
        errors = structural_errors(self.service, self.details.alternatives, self.details.criteria)
        if errors:
            self._errors(errors)
            return
        if self._save_editor(notify=False):
            self.show_ratings()

    def show_ratings(self):
        self._page("Bewertungen", "ratings")
        ttk.Label(self.body, text="Bewerten Sie jede Kombination von 1 (schlecht) bis 5 (sehr gut).").pack(anchor="w", pady=(0, 8))
        grid = self._scroll_area(self.body)
        d = self.details
        old = {(r.alternative_id, r.criterion_id): r for r in d.ratings}
        self.rating_variables = {}
        ttk.Label(grid, text="Alternative").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        for column, criterion in enumerate(d.criteria, 1):
            ttk.Label(grid, text=criterion.name, wraplength=140).grid(row=0, column=column, padx=8, pady=8)
        for row, alternative in enumerate(d.alternatives, 1):
            ttk.Label(grid, text=alternative.name, wraplength=180).grid(row=row, column=0, sticky="w", padx=8, pady=6)
            for column, criterion in enumerate(d.criteria, 1):
                key = (alternative.id, criterion.id)
                variable = tk.StringVar(value=str(old[key].value) if key in old else "")
                self.rating_variables[key] = variable
                ttk.Combobox(grid, textvariable=variable, values=("", "1", "2", "3", "4", "5"), state="readonly", width=8).grid(row=row, column=column, padx=8, pady=6)
        self._button("Zurück", self._back_to_editor)
        self._button("Speichern", self._save_ratings)
        self._button("Auswertung durchführen", self._evaluate)

    def _capture_ratings(self):
        old = {(r.alternative_id, r.criterion_id): r for r in self.details.ratings}
        ratings = []
        try:
            for key, variable in self.rating_variables.items():
                if variable.get().strip():
                    ratings.append(Rating(old[key].id if key in old else None, *key, int(variable.get())))
        except ValueError:
            self._error("Bewertungen müssen ganze Zahlen von 1 bis 5 sein.")
            return False
        errors = self.service.validate_for_evaluation(self.details.alternatives, self.details.criteria, ratings)
        # Missing entries are allowed when saving a draft, but not at evaluation.
        errors = [e for e in errors if "must have exactly one rating" not in e]
        if errors:
            self._errors(errors)
            return False
        self.details.ratings = ratings
        return True

    def _back_to_editor(self):
        if self._capture_ratings():
            self.show_editor()

    def _save_ratings(self):
        if self._capture_ratings():
            return self._persist()
        return False

    def _evaluate(self):
        if not self._capture_ratings():
            return
        errors = self.service.validate_for_evaluation(self.details.alternatives, self.details.criteria, self.details.ratings)
        if errors:
            self._errors(errors)
            return
        self.show_results()

    def _ranking_rows(self, ranking):
        names = {a.id: a.name for a in self.details.alternatives}
        return [(r.rank, names[r.alternative_id], display_number(r.score)) for r in ranking]

    def show_results(self):
        d = self.details
        try:
            scores = self.service.calculate_scores(d.alternatives, d.criteria, d.ratings)
            ranking = self.service.create_ranking(scores)
        except ValueError as error:
            self._errors([str(error)])
            return
        self._page("Ergebnis", "results")
        self._table(self.body, ("Rang", "Alternative", "Gesamtwert"), self._ranking_rows(ranking))
        self._button("Zurück zur Bewertung", self.show_ratings)
        self._button("Sensitivitätsanalyse", self.show_sensitivity)
        self._button("Speichern", self._persist)
        self._button("Zur Startseite", self._home)

    def show_sensitivity(self):
        self._page("Sensitivitätsanalyse", "sensitivity")
        ttk.Label(self.body, text="Änderungen sind nur vorübergehend. Die gespeicherten Gewichte bleiben unverändert.", wraplength=850).pack(anchor="w", pady=(0, 8))
        controls = ttk.Frame(self.body)
        controls.pack(fill="x")
        ttk.Label(controls, text="Kriterium").pack(side="left")
        selection = ttk.Combobox(controls, state="readonly", values=[f"{i}. {c.name}" for i, c in enumerate(self.details.criteria, 1)], width=30)
        selection.pack(side="left", padx=8)
        selection.current(0)
        ttk.Label(controls, text="Neues Gewicht (%)").pack(side="left")
        weight = tk.StringVar(value=str(self.details.criteria[0].weight))
        ttk.Entry(controls, textvariable=weight, width=12).pack(side="left", padx=8)
        selection.bind("<<ComboboxSelected>>", lambda event: weight.set(str(self.details.criteria[selection.current()].weight)))
        output = ttk.Frame(self.body)
        output.pack(fill="both", expand=True)
        self._table(output, ("Kriterium", "Ursprüngliches Gewicht (%)"), [(c.name, display_number(c.weight)) for c in self.details.criteria])

        def calculate():
            try:
                new_weight = parse_number(weight.get())
            except ValueError:
                self._error("Bitte geben Sie ein numerisches Gewicht ein.")
                return
            d = self.details
            try:
                result = self.service.calculate_sensitivity(d.alternatives, d.criteria, d.ratings, d.criteria[selection.current()].id, new_weight)
            except ValueError as error:
                self._errors([str(error)])
                return
            for child in output.winfo_children():
                child.destroy()
            self._table(output, ("Kriterium", "Ursprünglich (%)", "Szenario (%)"),
                        [(c.name, display_number(result["original_weights"][c.id]), display_number(result["scenario_weights"][c.id])) for c in d.criteria], height=4)
            rankings = ttk.Frame(output)
            rankings.pack(fill="both", expand=True)
            for label, key in (("Ursprüngliches Ergebnis", "original_ranking"), ("Szenario", "scenario_ranking")):
                group = ttk.LabelFrame(rankings, text=label, padding=4)
                group.pack(side="left", fill="both", expand=True, padx=4)
                self._table(group, ("Rang", "Alternative", "Gesamtwert"), self._ranking_rows(result[key]), height=5)
        ttk.Button(controls, text="Analyse durchführen", command=calculate).pack(side="left")
        self._button("Zurück zum Ergebnis", self.show_results)

    def _can_leave(self):
        if self.details is None:
            return True
        if self.view == "editor":
            self._capture_editor()
        elif self.view == "ratings" and not self._capture_ratings():
            return False
        if self.details == self.saved:
            return True
        answer = messagebox.askyesnocancel("Ungespeicherte Änderungen", "Änderungen vor dem Verlassen speichern?", parent=self.root)
        if answer is None:
            return False
        if answer:
            return self._save_editor(False) if self.view == "editor" else self._persist(False)
        return True

    def _home(self):
        if self._can_leave():
            self.show_start()

    def _close(self):
        if self._can_leave():
            self.root.destroy()
