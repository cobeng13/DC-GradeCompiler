import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openpyxl import Workbook

from ingest import ISSUE_COLUMNS, PASSED_COLUMNS, is_blank, normalize_name


def write_sheet(
    workbook: Workbook, title: str, columns: List[str], rows: List[Dict[str, Any]]
) -> None:
    worksheet = workbook.create_sheet(title=title)
    worksheet.append(columns)

    for row in rows:
        worksheet.append([row.get(column, "") for column in columns])

    for column_cells in worksheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        worksheet.column_dimensions[column_cells[0].column_letter].width = min(
            max(max_length + 2, 12), 60
        )


def year_sheet_name(section: Any) -> str:
    if is_blank(section):
        return "Unassigned"

    match = re.match(r"\s*(\d+)", str(section))
    if not match:
        return "Unassigned"
    return f"Year{match.group(1)}"


def safe_sheet_title(title: str, used_titles: set) -> str:
    safe_title = re.sub(r"[\[\]:*?/\\]", "_", title)[:31] or "Sheet"
    candidate = safe_title
    suffix = 1

    while candidate in used_titles:
        suffix_text = f"_{suffix}"
        candidate = f"{safe_title[:31 - len(suffix_text)]}{suffix_text}"
        suffix += 1

    used_titles.add(candidate)
    return candidate


def build_matrix_students(
    masterlist_records: List[Dict[str, Any]], result_rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    students: List[Dict[str, Any]] = []
    indexes: Dict[str, int] = {}

    for record in masterlist_records:
        normalized_name = record.get("NormalizedName") or normalize_name(
            record.get("StudentName")
        )
        if not normalized_name:
            continue
        indexes[normalized_name] = len(students)
        students.append(
            {
                "StudentName": record.get("StudentName"),
                "Section": record.get("Section"),
                "NormalizedName": normalized_name,
            }
        )

    for result in result_rows:
        normalized_name = normalize_name(result.get("StudentName"))
        if not normalized_name:
            continue

        if normalized_name not in indexes:
            indexes[normalized_name] = len(students)
            students.append(
                {
                    "StudentName": result.get("StudentName"),
                    "Section": result.get("Section"),
                    "NormalizedName": normalized_name,
                }
            )
            continue

        student = students[indexes[normalized_name]]
        if is_blank(student.get("Section")) and not is_blank(result.get("Section")):
            student["Section"] = result.get("Section")

    return students


def matrix_courses(result_rows: List[Dict[str, Any]]) -> List[str]:
    courses = []
    seen_courses = set()
    for result in result_rows:
        course = result.get("Course")
        if is_blank(course) or course in seen_courses:
            continue
        seen_courses.add(course)
        courses.append(course)
    return courses


def write_matrix_report(
    output_file: Path,
    masterlist_records: List[Dict[str, Any]],
    result_rows: List[Dict[str, Any]],
    result_lookup: Dict[Tuple[str, str], Any],
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    courses = matrix_courses(result_rows)

    students = build_matrix_students(masterlist_records, result_rows)
    students_by_sheet: Dict[str, List[Dict[str, Any]]] = {}
    for student in students:
        sheet_name = year_sheet_name(student.get("Section"))
        students_by_sheet.setdefault(sheet_name, []).append(student)

    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    used_titles = set()
    sheet_order = sorted(
        students_by_sheet,
        key=lambda name: (name == "Unassigned", name),
    )
    if not sheet_order:
        sheet_order = ["Unassigned"]
        students_by_sheet["Unassigned"] = []

    for sheet_name in sheet_order:
        worksheet = workbook.create_sheet(safe_sheet_title(sheet_name, used_titles))
        columns = ["Name", "Section"] + courses
        worksheet.append(columns)

        for student in sorted(
            students_by_sheet[sheet_name],
            key=lambda item: (
                str(item.get("Section") or ""),
                str(item.get("StudentName") or ""),
            ),
        ):
            normalized_name = student.get("NormalizedName")
            row = [student.get("StudentName"), student.get("Section")]
            row.extend(
                result_lookup.get((normalized_name, course), "") for course in courses
            )
            worksheet.append(row)

        for column_cells in worksheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(
                max(max_length + 2, 12), 50
            )

    workbook.save(output_file)


def generate_pass_fail_matrix_report(
    output_file: Path,
    masterlist_records: List[Dict[str, Any]],
    result_rows: List[Dict[str, Any]],
) -> None:
    result_lookup: Dict[Tuple[str, str], str] = {}
    for result in result_rows:
        normalized_name = normalize_name(result.get("StudentName"))
        course = result.get("Course")
        status = result.get("Status")
        if normalized_name and not is_blank(course) and status in {"Passed", "Fail"}:
            result_lookup[(normalized_name, course)] = status

    write_matrix_report(output_file, masterlist_records, result_rows, result_lookup)


def generate_midterm_grade_matrix_report(
    output_file: Path,
    masterlist_records: List[Dict[str, Any]],
    result_rows: List[Dict[str, Any]],
) -> None:
    result_lookup: Dict[Tuple[str, str], Any] = {}
    for result in result_rows:
        normalized_name = normalize_name(result.get("StudentName"))
        course = result.get("Course")
        grade = result.get("MidtermGrade")
        if normalized_name and not is_blank(course) and not is_blank(grade):
            result_lookup[(normalized_name, course)] = grade

    write_matrix_report(output_file, masterlist_records, result_rows, result_lookup)


def generate_workbook_reports(
    output_file: Path,
    pass_fail_output_file: Path,
    grade_output_file: Path,
    masterlist_records: List[Dict[str, Any]],
    result_rows: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    passed_students = [
        result for result in result_rows if result.get("Status") == "Passed"
    ]

    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    write_sheet(workbook, "PassedStudents", PASSED_COLUMNS, passed_students)
    write_sheet(workbook, "Issues", ISSUE_COLUMNS, issues)
    workbook.save(output_file)

    generate_pass_fail_matrix_report(
        pass_fail_output_file, masterlist_records, result_rows
    )
    generate_midterm_grade_matrix_report(
        grade_output_file, masterlist_records, result_rows
    )
