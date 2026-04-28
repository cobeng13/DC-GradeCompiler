import argparse
from contextlib import closing
from pathlib import Path
from typing import Optional, Tuple

from ingest import ingest_folder
from reports import generate_workbook_reports
from storage import (
    DEFAULT_DB_PATH,
    connect,
    load_batch_for_reports,
    save_ingest_result,
)


def generate_report(
    input_folder: Path,
    output_file: Path,
    pass_fail_output_file: Path,
    grade_output_file: Path,
    passing_grade: float,
    masterlist_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    batch_label: str = "",
) -> Tuple[int, int, int, int]:
    result = ingest_folder(input_folder, masterlist_path, passing_grade)

    with closing(connect(db_path)) as connection:
        batch_id = save_ingest_result(connection, result, batch_label)
        report_data = load_batch_for_reports(connection, batch_id)

    generate_workbook_reports(
        output_file,
        pass_fail_output_file,
        grade_output_file,
        report_data["masterlist_records"],
        report_data["result_rows"],
        report_data["issues"],
    )

    return result.files_processed, result.passed_count, len(result.issues), batch_id


def export_existing_batch(
    db_path: Path,
    output_file: Path,
    pass_fail_output_file: Path,
    grade_output_file: Path,
    batch_id: Optional[int] = None,
) -> int:
    with closing(connect(db_path)) as connection:
        report_data = load_batch_for_reports(connection, batch_id)

    generate_workbook_reports(
        output_file,
        pass_fail_output_file,
        grade_output_file,
        report_data["masterlist_records"],
        report_data["result_rows"],
        report_data["issues"],
    )
    return len(report_data["result_rows"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest grading sheets into SQLite and generate midterm reports."
    )
    parser.add_argument(
        "--input",
        default="input/grades",
        help="Folder containing .xlsx and .xlsm grading sheets.",
    )
    parser.add_argument(
        "--output",
        default="output/passed_midterm_report.xlsx",
        help="Path for the generated Excel report.",
    )
    parser.add_argument(
        "--pass-fail-output",
        default="output/midterm_exam_pass_fail_report.xlsx",
        help="Path for the generated Midterm Exam Pass/Fail matrix report.",
    )
    parser.add_argument(
        "--grade-output",
        default="output/midterm_grade_report.xlsx",
        help="Path for the generated Midterm Grade matrix report.",
    )
    parser.add_argument(
        "--passing-grade",
        type=float,
        default=75,
        help="Minimum MidtermGrade required to pass.",
    )
    parser.add_argument(
        "--masterlist",
        default="input/masterlist/masterlist.csv",
        help="Path to masterlist.csv used to fill missing student numbers.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path.",
    )
    parser.add_argument(
        "--batch-label",
        default="",
        help="Optional label saved with this ingest batch.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Generate reports from an existing database batch without ingesting files.",
    )
    parser.add_argument(
        "--batch-id",
        type=int,
        default=None,
        help="Batch ID to export when using --export-only. Defaults to latest batch.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    output_file = Path(args.output)
    pass_fail_output_file = Path(args.pass_fail_output)
    grade_output_file = Path(args.grade_output)
    db_path = Path(args.db)

    if args.export_only:
        grade_count = export_existing_batch(
            db_path,
            output_file,
            pass_fail_output_file,
            grade_output_file,
            args.batch_id,
        )
        print("Midterm reports exported from database.")
        print(f"Grade records exported: {grade_count}")
        print(f"Output file: {output_file.resolve()}")
        print(f"Pass/fail matrix file: {pass_fail_output_file.resolve()}")
        print(f"Midterm grade matrix file: {grade_output_file.resolve()}")
        return

    files_processed, passed_count, issue_count, batch_id = generate_report(
        Path(args.input),
        output_file,
        pass_fail_output_file,
        grade_output_file,
        args.passing_grade,
        Path(args.masterlist),
        db_path,
        args.batch_label,
    )

    print("Midterm ingest and reports generated.")
    print(f"Batch ID: {batch_id}")
    print(f"Files processed: {files_processed}")
    print(f"Passed students found: {passed_count}")
    print(f"Issues found: {issue_count}")
    print(f"Database file: {db_path.resolve()}")
    print(f"Output file: {output_file.resolve()}")
    print(f"Pass/fail matrix file: {pass_fail_output_file.resolve()}")
    print(f"Midterm grade matrix file: {grade_output_file.resolve()}")


if __name__ == "__main__":
    main()
