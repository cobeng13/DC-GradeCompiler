import sys
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db_editor import (
    apply_student_merge_batch,
    apply_student_merge,
    list_students_for_editor,
    preview_student_merge,
    suggest_student_merges,
    undo_student_merge,
    update_student_identity,
)
from storage import connect, initialize_database


class DbEditorTests(unittest.TestCase):
    def open_db(self):
        connection = connect(Path(":memory:"))
        initialize_database(connection)
        return connection

    def add_student(self, connection, name, number="", section="1A"):
        normalized_name = " ".join(
            "".join(character.lower() if character.isalnum() else " " for character in name).split()
        )
        cursor = connection.execute(
            """
            INSERT INTO students
                (display_name, student_number, section, normalized_name)
            VALUES (?, ?, ?, ?)
            """,
            (name, number, section, normalized_name),
        )
        return int(cursor.lastrowid)

    def add_grade(self, connection, student_id, batch_id, course, name, number="", section="1A"):
        normalized_name = " ".join(
            "".join(character.lower() if character.isalnum() else " " for character in name).split()
        )
        connection.execute(
            """
            INSERT INTO grade_records
                (
                    batch_id, student_id, course, student_name, student_number,
                    section, normalized_name, midterm_exam, midterm_grade, status
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                student_id,
                course,
                name,
                number,
                section,
                normalized_name,
                "40",
                90,
                "Passed",
            ),
        )

    def add_batch_student(self, connection, student_id, batch_id, name, number="", section="1A"):
        normalized_name = " ".join(
            "".join(character.lower() if character.isalnum() else " " for character in name).split()
        )
        connection.execute(
            """
            INSERT INTO batch_students
                (batch_id, student_id, student_name, student_number, section, normalized_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (batch_id, student_id, name, number, section, normalized_name),
        )

    def add_batch(self, connection):
        cursor = connection.execute(
            """
            INSERT INTO ingest_batches
                (label, created_at, passing_grade, files_processed, grade_count, issue_count)
            VALUES ('test', '2026-04-29T00:00:00', 75, 1, 0, 0)
            """
        )
        return int(cursor.lastrowid)

    def test_suggestions_include_matching_numbers_and_short_name_subsets(self):
        with closing(self.open_db()) as connection:
            left = self.add_student(connection, "Andaya, Isiah Ximuel Carandang", "2024-001", "1A")
            right = self.add_student(connection, "Andaya, Isiah Ximuel", "", "1A")
            other = self.add_student(connection, "Different Spelling", "2024-001", "2A")
            mismatch = self.add_student(connection, "Andaya, Isiah", "", "2A")
            rillorta_long = self.add_student(connection, "Rillorta, Prince Jasper", "", "1A")
            rillorta_short = self.add_student(connection, "Rillorta, Prince", "", "1A")
            connection.commit()

            suggestions = suggest_student_merges(connection)

        suggested_ids = {tuple(item["StudentIds"]) for item in suggestions}
        self.assertIn(tuple(sorted([left, right])), suggested_ids)
        self.assertIn(tuple(sorted([left, other])), suggested_ids)
        self.assertIn(tuple(sorted([left, mismatch])), suggested_ids)
        self.assertIn(tuple(sorted([rillorta_long, rillorta_short])), suggested_ids)
        subset_suggestion = next(
            item for item in suggestions if item["StudentIds"] == sorted([left, right])
        )
        self.assertIn("Short-name subset", subset_suggestion["Reasons"])
        self.assertEqual(subset_suggestion["Confidence"], 70)
        mismatch_suggestion = next(
            item for item in suggestions if item["StudentIds"] == sorted([left, mismatch])
        )
        self.assertIn("Section mismatch", mismatch_suggestion["Reasons"])
        self.assertEqual(mismatch_suggestion["Confidence"], 60)
        rillorta_suggestion = next(
            item
            for item in suggestions
            if item["StudentIds"] == sorted([rillorta_long, rillorta_short])
        )
        self.assertEqual(rillorta_suggestion["CanonicalStudentId"], rillorta_long)
        self.assertIn("Rillorta, Prince Jasper", rillorta_suggestion["MergeTo"])

    def test_suggestions_reject_shared_surname_or_trailing_token_only(self):
        with closing(self.open_db()) as connection:
            catibog_left = self.add_student(connection, "Catibog, Danielle Ysabel Lanip", "25137132", "1A")
            catibog_right = self.add_student(connection, "Catibog, Denise Alexa Lanip", "24132886", "2A")
            deguzman_left = self.add_student(connection, "De Guzman, Jan Gabriel Banawan", "23130206", "3A")
            deguzman_right = self.add_student(connection, "De Guzman, Angelica Rosales", "23129944", "1A")
            bautista_left = self.add_student(connection, "Bautista, Eloiza Katherine Calayan", "23130377", "3A")
            bautista_right = self.add_student(connection, "Bautista, Elaiza Kathrina Calayan", "23130378", "3A")
            connection.commit()

            suggestions = suggest_student_merges(connection)

        suggested_ids = {tuple(item["StudentIds"]) for item in suggestions}
        self.assertNotIn(tuple(sorted([catibog_left, catibog_right])), suggested_ids)
        self.assertNotIn(tuple(sorted([deguzman_left, deguzman_right])), suggested_ids)
        self.assertNotIn(tuple(sorted([bautista_left, bautista_right])), suggested_ids)

    def test_applied_merge_is_removed_from_suggestions_until_undone(self):
        with closing(self.open_db()) as connection:
            left = self.add_student(connection, "Jane A. Student", "2024-001", "1A")
            right = self.add_student(connection, "Jane Student", "2024-001", "1A")
            connection.commit()

            before_merge = {
                tuple(item["StudentIds"]) for item in suggest_student_merges(connection)
            }
            merge_id = apply_student_merge(connection, [left, right])
            after_merge = {
                tuple(item["StudentIds"]) for item in suggest_student_merges(connection)
            }
            undo_student_merge(connection, merge_id)
            after_undo = {
                tuple(item["StudentIds"]) for item in suggest_student_merges(connection)
            }

        suggestion_key = tuple(sorted([left, right]))
        self.assertIn(suggestion_key, before_merge)
        self.assertNotIn(suggestion_key, after_merge)
        self.assertIn(suggestion_key, after_undo)

    def test_merge_updates_linked_rows_and_denormalized_identity_fields(self):
        with closing(self.open_db()) as connection:
            batch_id = self.add_batch(connection)
            canonical = self.add_student(connection, "Jane A. Student", "2024-001", "1A")
            alias = self.add_student(connection, "Jane Student", "", "1A")
            self.add_grade(connection, canonical, batch_id, "CourseA", "Jane A. Student", "2024-001", "1A")
            self.add_grade(connection, alias, batch_id, "CourseB", "Jane Student", "", "1A")
            self.add_batch_student(connection, alias, batch_id, "Jane Student", "", "1A")
            connection.commit()

            merge_id = apply_student_merge(connection, [canonical, alias])
            students = list_students_for_editor(connection)
            grade_rows = connection.execute(
                "SELECT student_id, student_name, student_number, section FROM grade_records ORDER BY course"
            ).fetchall()
            batch_row = connection.execute(
                "SELECT student_id, student_name, student_number FROM batch_students"
            ).fetchone()

        self.assertGreater(merge_id, 0)
        self.assertEqual([row["student_id"] for row in grade_rows], [canonical, canonical])
        self.assertEqual({row["student_name"] for row in grade_rows}, {"Jane A. Student"})
        self.assertEqual({row["student_number"] for row in grade_rows}, {"2024-001"})
        self.assertEqual(batch_row["student_id"], canonical)
        self.assertEqual(batch_row["student_name"], "Jane A. Student")
        self.assertEqual(len(students), 2)

    def test_merge_can_use_user_selected_canonical_student(self):
        with closing(self.open_db()) as connection:
            batch_id = self.add_batch(connection)
            default_canonical = self.add_student(connection, "Jane A. Student", "2024-001", "1A")
            selected_canonical = self.add_student(connection, "Jane Student", "", "1A")
            self.add_grade(
                connection,
                default_canonical,
                batch_id,
                "CourseA",
                "Jane A. Student",
                "2024-001",
                "1A",
            )
            self.add_grade(
                connection,
                selected_canonical,
                batch_id,
                "CourseB",
                "Jane Student",
                "",
                "1A",
            )
            connection.commit()

            preview = preview_student_merge(
                connection,
                [default_canonical, selected_canonical],
                canonical_student_id=selected_canonical,
            )
            apply_student_merge(
                connection,
                [default_canonical, selected_canonical],
                canonical_student_id=selected_canonical,
            )
            grade_rows = connection.execute(
                "SELECT student_id, student_name, student_number FROM grade_records ORDER BY course"
            ).fetchall()

        self.assertEqual(preview["canonical_student"]["id"], selected_canonical)
        self.assertEqual(
            [row["student_id"] for row in grade_rows],
            [selected_canonical, selected_canonical],
        )
        self.assertEqual({row["student_name"] for row in grade_rows}, {"Jane Student"})
        self.assertEqual({row["student_number"] for row in grade_rows}, {"2024-001"})

    def test_merge_blocks_same_batch_course_conflicts(self):
        with closing(self.open_db()) as connection:
            batch_id = self.add_batch(connection)
            left = self.add_student(connection, "Jane A. Student", "2024-001", "1A")
            right = self.add_student(connection, "Jane Student", "", "1A")
            self.add_grade(connection, left, batch_id, "CourseA", "Jane A. Student", "2024-001", "1A")
            self.add_grade(connection, right, batch_id, "CourseA", "Jane Student", "", "1A")
            connection.commit()

            preview = preview_student_merge(connection, [left, right])
            with self.assertRaises(ValueError):
                apply_student_merge(connection, [left, right])

        self.assertEqual(len(preview["conflicts"]), 1)

    def test_batch_merge_applies_selected_candidates_and_skips_conflicts(self):
        with closing(self.open_db()) as connection:
            batch_id = self.add_batch(connection)
            left = self.add_student(connection, "Jane A. Student", "2024-001", "1A")
            right = self.add_student(connection, "Jane Student", "2024-001", "1A")
            conflict_left = self.add_student(connection, "Course Conflict A", "2024-002", "1A")
            conflict_right = self.add_student(connection, "Course Conflict B", "2024-002", "1A")
            self.add_grade(connection, conflict_left, batch_id, "CourseA", "Course Conflict A", "2024-002", "1A")
            self.add_grade(connection, conflict_right, batch_id, "CourseA", "Course Conflict B", "2024-002", "1A")
            connection.commit()

            suggestions = suggest_student_merges(connection)
            selected = [
                item
                for item in suggestions
                if item["StudentIds"] in [sorted([left, right]), sorted([conflict_left, conflict_right])]
            ]
            result = apply_student_merge_batch(connection, selected)

        self.assertEqual(result["AppliedCount"], 1)
        self.assertEqual(result["SkippedCount"], 1)
        self.assertEqual(result["Skipped"][0]["Reason"], "Conflicting grade rows")

    def test_undo_restores_original_linked_rows(self):
        with closing(self.open_db()) as connection:
            batch_id = self.add_batch(connection)
            canonical = self.add_student(connection, "Jane A. Student", "2024-001", "1A")
            alias = self.add_student(connection, "Jane Student", "", "1A")
            self.add_grade(connection, alias, batch_id, "CourseB", "Jane Student", "", "1A")
            self.add_batch_student(connection, alias, batch_id, "Jane Student", "", "1A")
            connection.commit()

            merge_id = apply_student_merge(connection, [canonical, alias])
            undo_student_merge(connection, merge_id)
            grade_row = connection.execute(
                "SELECT student_id, student_name, student_number FROM grade_records"
            ).fetchone()
            history = connection.execute(
                "SELECT status FROM student_merge_history WHERE id = ?", (merge_id,)
            ).fetchone()

        self.assertEqual(grade_row["student_id"], alias)
        self.assertEqual(grade_row["student_name"], "Jane Student")
        self.assertEqual(grade_row["student_number"], "")
        self.assertEqual(history["status"], "reverted")

    def test_identity_edit_updates_student_and_linked_rows(self):
        with closing(self.open_db()) as connection:
            batch_id = self.add_batch(connection)
            student_id = self.add_student(connection, "Old Name", "", "")
            self.add_grade(connection, student_id, batch_id, "CourseA", "Old Name", "", "")
            self.add_batch_student(connection, student_id, batch_id, "Old Name", "", "")
            connection.commit()

            update_student_identity(connection, student_id, "New Name", "2024-999", "3C")
            student = connection.execute(
                "SELECT display_name, student_number, section, normalized_name FROM students"
            ).fetchone()
            grade = connection.execute(
                "SELECT student_name, student_number, section, normalized_name FROM grade_records"
            ).fetchone()

        self.assertEqual(student["display_name"], "New Name")
        self.assertEqual(student["student_number"], "2024-999")
        self.assertEqual(student["section"], "3C")
        self.assertEqual(grade["student_name"], "New Name")
        self.assertEqual(grade["normalized_name"], "new name")


if __name__ == "__main__":
    unittest.main()
