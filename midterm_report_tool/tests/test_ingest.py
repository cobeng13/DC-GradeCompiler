import csv
import shutil
import sys
import unittest
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest import (
    clean_student_name,
    find_column_map,
    ingest_folder,
    normalize_name,
    parse_filename,
    to_number,
)
from storage import connect, load_batch_for_reports, save_ingest_result


class IngestTests(unittest.TestCase):
    @contextmanager
    def workspace_tempdir(self):
        temp_root = Path(__file__).resolve().parents[1] / ".test_tmp"
        temp_root.mkdir(exist_ok=True)
        temp_dir = temp_root / f"case_{uuid.uuid4().hex}"
        temp_dir.mkdir()
        try:
            yield temp_dir
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def write_masterlist(self, folder: Path) -> Path:
        masterlist_path = folder / "masterlist.csv"
        with masterlist_path.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(
                file_obj, fieldnames=["Name", "ClassNumber", "Section"]
            )
            writer.writeheader()
            writer.writerow(
                {"Name": "Jane A. Student", "ClassNumber": "2024-001", "Section": "1A"}
            )
        return masterlist_path

    def write_workbook(self, path: Path, rows) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        for row in rows:
            worksheet.append(row)
        workbook.save(path)

    def test_helpers_parse_expected_values(self):
        self.assertEqual(parse_filename("2A_Org_Med_Lec.xlsm")[:2], ("2A", "Org_Med_Lec"))
        self.assertEqual(normalize_name(" Jane   A. Student "), "jane a student")
        self.assertEqual(
            clean_student_name("  2  Catibog, Denise Alexa Lanip         "),
            "Catibog, Denise Alexa Lanip",
        )
        self.assertEqual(
            normalize_name(" 10  Latorre, Jehaila Angel Carisma       "),
            "latorre jehaila angel carisma",
        )
        self.assertEqual(normalize_name("Pe\u00f1a, Jos\u00e9 Ni\u00f1o"), "pena jose nino")
        self.assertEqual(
            normalize_name("Visle\u5e3do, Dennice Dimaculangan"),
            "visleno dennice dimaculangan",
        )
        self.assertEqual(
            normalize_name("VisleNo, Dennice Dimaculangan"),
            "visleno dennice dimaculangan",
        )
        self.assertEqual(
            normalize_name("Visle\u00c3\u00b1o, Dennice Dimaculangan"),
            "visleno dennice dimaculangan",
        )
        self.assertEqual(to_number(" 85% "), 85.0)
        self.assertEqual(
            find_column_map(("Name", "ME", "Midterm Grade")),
            {"StudentName": 1, "MidtermExam": 2, "MidtermGrade": 3},
        )

    def test_enye_normalization_matches_masterlist_to_workbook_name(self):
        with self.workspace_tempdir() as base:
            grades = base / "grades"
            grades.mkdir()
            masterlist_path = base / "masterlist.csv"
            with masterlist_path.open("w", newline="", encoding="utf-8") as file_obj:
                writer = csv.DictWriter(
                    file_obj, fieldnames=["Name", "ClassNumber", "Section"]
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Name": "Pe\u00f1a, Jos\u00e9 Ni\u00f1o",
                        "ClassNumber": "2024-099",
                        "Section": "1A",
                    }
                )
            self.write_workbook(
                grades / "1A_Test_Course.xlsx",
                [
                    ["Name", "ME", "Midterm Grade"],
                    ["Pena, Jose Nino", 42, 91],
                ],
            )

            result = ingest_folder(grades, masterlist_path, 75)

        self.assertEqual(len(result.result_rows), 1)
        self.assertEqual(result.result_rows[0]["StudentNumber"], "2024-099")
        self.assertEqual(result.result_rows[0]["NormalizedName"], "pena jose nino")

    def test_ingest_fills_missing_student_number_and_flags_bad_rows(self):
        with self.workspace_tempdir() as base:
            grades = base / "grades"
            grades.mkdir()
            masterlist_path = self.write_masterlist(base)
            self.write_workbook(
                grades / "1A_Test_Course.xlsx",
                [
                    ["Name", "ME", "Midterm Grade"],
                    ["Jane A. Student", 42, 91],
                    ["Broken Grade", 30, "not a number"],
                ],
            )

            result = ingest_folder(grades, masterlist_path, 75)

        self.assertEqual(result.files_processed, 1)
        self.assertEqual(len(result.result_rows), 1)
        self.assertEqual(result.result_rows[0]["StudentNumber"], "2024-001")
        self.assertEqual(result.result_rows[0]["Status"], "Passed")
        issue_types = {issue["IssueType"] for issue in result.issues}
        self.assertIn("MissingStudentNumberColumn", issue_types)
        self.assertIn("InvalidMidtermGrade", issue_types)

    def test_ingest_ignores_grade_sheet_student_number(self):
        with self.workspace_tempdir() as base:
            grades = base / "grades"
            grades.mkdir()
            masterlist_path = self.write_masterlist(base)
            self.write_workbook(
                grades / "1A_Test_Course.xlsx",
                [
                    ["Student Number", "Student Name", "Midterm Exam", "Midterm Grade"],
                    ["RANDOM-GRADESHEET-ID", "Jane A. Student", 42, 91],
                ],
            )

            result = ingest_folder(grades, masterlist_path, 75)

        self.assertEqual(len(result.result_rows), 1)
        self.assertEqual(result.result_rows[0]["StudentNumber"], "2024-001")
        self.assertNotEqual(
            result.result_rows[0]["StudentNumber"], "RANDOM-GRADESHEET-ID"
        )

    def test_ingest_strips_leading_roster_number_from_student_name(self):
        with self.workspace_tempdir() as base:
            grades = base / "grades"
            grades.mkdir()
            masterlist_path = base / "masterlist.csv"
            with masterlist_path.open("w", newline="", encoding="utf-8") as file_obj:
                writer = csv.DictWriter(
                    file_obj, fieldnames=["Name", "ClassNumber", "Section"]
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Name": "Catibog, Denise Alexa Lanip",
                        "ClassNumber": "2024-222",
                        "Section": "2A",
                    }
                )
            self.write_workbook(
                grades / "2A_QC_2_LEC.xlsx",
                [
                    ["Student Number", "Student Name", "Midterm Exam", "Midterm Grade"],
                    ["BAD-ID", "  2  Catibog, Denise Alexa Lanip         ", 42, 91],
                ],
            )

            result = ingest_folder(grades, masterlist_path, 75)

        self.assertEqual(len(result.result_rows), 1)
        self.assertEqual(
            result.result_rows[0]["StudentName"], "Catibog, Denise Alexa Lanip"
        )
        self.assertEqual(result.result_rows[0]["StudentNumber"], "2024-222")

    def test_missing_masterlist_match_leaves_student_number_blank(self):
        with self.workspace_tempdir() as base:
            grades = base / "grades"
            grades.mkdir()
            masterlist_path = self.write_masterlist(base)
            self.write_workbook(
                grades / "1A_Test_Course.xlsx",
                [
                    ["Student Number", "Student Name", "Midterm Exam", "Midterm Grade"],
                    ["RANDOM-GRADESHEET-ID", "Unknown Student", 42, 91],
                ],
            )

            result = ingest_folder(grades, masterlist_path, 75)

        self.assertEqual(len(result.result_rows), 1)
        self.assertEqual(result.result_rows[0]["StudentNumber"], "")
        self.assertIn("not found in masterlist", result.result_rows[0]["Notes"])

    def test_mismatched_workbook_creates_reviewable_issue(self):
        with self.workspace_tempdir() as base:
            grades = base / "grades"
            grades.mkdir()
            masterlist_path = self.write_masterlist(base)
            self.write_workbook(
                grades / "faculty_upload.xlsx",
                [
                    ["Random", "Columns", "Only"],
                    ["A", "B", "C"],
                ],
            )

            result = ingest_folder(grades, masterlist_path, 75)

        self.assertEqual(result.files_processed, 0)
        issue_types = {issue["IssueType"] for issue in result.issues}
        self.assertIn("MissingRequiredColumns", issue_types)
        self.assertIn("NoProcessableSheet", issue_types)

    def test_database_round_trip_supports_report_data(self):
        with self.workspace_tempdir() as base:
            grades = base / "grades"
            grades.mkdir()
            masterlist_path = self.write_masterlist(base)
            self.write_workbook(
                grades / "1A_Test_Course.xlsx",
                [
                    ["Student Number", "Student Name", "Midterm Exam", "Midterm Grade"],
                    ["", "Jane A. Student", 42, 91],
                ],
            )
            result = ingest_folder(grades, masterlist_path, 75)

            with closing(connect(base / "grades.sqlite3")) as connection:
                batch_id = save_ingest_result(connection, result, "test")
                report_data = load_batch_for_reports(connection, batch_id)

        self.assertEqual(len(report_data["result_rows"]), 1)
        self.assertEqual(report_data["result_rows"][0]["Course"], "Test_Course")
        self.assertGreaterEqual(len(report_data["masterlist_records"]), 1)


if __name__ == "__main__":
    unittest.main()
