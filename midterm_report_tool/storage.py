import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ingest import IngestResult, normalize_name


DEFAULT_DB_PATH = Path("data/grade_compiler.sqlite3")


SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,
    created_at TEXT NOT NULL,
    passing_grade REAL NOT NULL,
    files_processed INTEGER NOT NULL,
    grade_count INTEGER NOT NULL,
    issue_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT,
    section TEXT,
    course TEXT,
    processed INTEGER NOT NULL,
    notes TEXT,
    FOREIGN KEY (batch_id) REFERENCES ingest_batches(id)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_name TEXT NOT NULL UNIQUE,
    display_name TEXT,
    student_number TEXT,
    section TEXT
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS batch_students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    student_id INTEGER,
    student_name TEXT,
    student_number TEXT,
    section TEXT,
    normalized_name TEXT,
    FOREIGN KEY (batch_id) REFERENCES ingest_batches(id),
    FOREIGN KEY (student_id) REFERENCES students(id)
);

CREATE TABLE IF NOT EXISTS grade_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    source_file_id INTEGER,
    student_id INTEGER,
    course_id INTEGER,
    source_file TEXT,
    section TEXT,
    course TEXT,
    student_number TEXT,
    student_name TEXT,
    normalized_name TEXT,
    midterm_exam TEXT,
    midterm_grade REAL,
    status TEXT,
    notes TEXT,
    raw_row_json TEXT,
    FOREIGN KEY (batch_id) REFERENCES ingest_batches(id),
    FOREIGN KEY (source_file_id) REFERENCES source_files(id),
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (course_id) REFERENCES courses(id)
);

CREATE TABLE IF NOT EXISTS ingest_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    source_file_id INTEGER,
    source_file TEXT,
    row_number TEXT,
    issue_type TEXT NOT NULL,
    details TEXT,
    raw_student_number TEXT,
    raw_student_name TEXT,
    raw_midterm_exam TEXT,
    raw_midterm_grade TEXT,
    FOREIGN KEY (batch_id) REFERENCES ingest_batches(id),
    FOREIGN KEY (source_file_id) REFERENCES source_files(id)
);
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _source_file_id_by_name(
    connection: sqlite3.Connection, batch_id: int
) -> Dict[str, int]:
    rows = connection.execute(
        "SELECT id, file_name FROM source_files WHERE batch_id = ?", (batch_id,)
    ).fetchall()
    return {row["file_name"]: row["id"] for row in rows}


def upsert_student(
    connection: sqlite3.Connection,
    normalized_name: str,
    display_name: Any,
    student_number: Any,
    section: Any,
) -> Optional[int]:
    if not normalized_name:
        return None

    connection.execute(
        """
        INSERT INTO students (normalized_name, display_name, student_number, section)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(normalized_name) DO UPDATE SET
            display_name = CASE
                WHEN excluded.display_name != '' THEN excluded.display_name
                ELSE students.display_name
            END,
            student_number = CASE
                WHEN excluded.student_number != '' THEN excluded.student_number
                ELSE students.student_number
            END,
            section = CASE
                WHEN excluded.section != '' THEN excluded.section
                ELSE students.section
            END
        """,
        (
            normalized_name,
            _as_text(display_name),
            _as_text(student_number),
            _as_text(section),
        ),
    )
    row = connection.execute(
        "SELECT id FROM students WHERE normalized_name = ?", (normalized_name,)
    ).fetchone()
    return int(row["id"]) if row else None


def upsert_course(connection: sqlite3.Connection, course: Any) -> Optional[int]:
    course_name = _as_text(course)
    if not course_name:
        return None

    connection.execute(
        "INSERT INTO courses (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
        (course_name,),
    )
    row = connection.execute(
        "SELECT id FROM courses WHERE name = ?", (course_name,)
    ).fetchone()
    return int(row["id"]) if row else None


def save_ingest_result(
    connection: sqlite3.Connection,
    result: IngestResult,
    label: str = "",
) -> int:
    initialize_database(connection)
    cursor = connection.execute(
        """
        INSERT INTO ingest_batches
            (label, created_at, passing_grade, files_processed, grade_count, issue_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            label,
            datetime.now().isoformat(timespec="seconds"),
            result.passing_grade,
            result.files_processed,
            len(result.result_rows),
            len(result.issues),
        ),
    )
    batch_id = int(cursor.lastrowid)

    for source in result.source_files:
        connection.execute(
            """
            INSERT INTO source_files
                (batch_id, file_name, file_path, section, course, processed, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                source.get("SourceFile"),
                source.get("Path"),
                source.get("Section"),
                source.get("Course"),
                1 if source.get("Processed") else 0,
                source.get("Notes"),
            ),
        )

    source_file_ids = _source_file_id_by_name(connection, batch_id)

    for record in result.masterlist_records:
        student_id = upsert_student(
            connection,
            record.get("NormalizedName") or normalize_name(record.get("StudentName")),
            record.get("StudentName"),
            record.get("StudentNumber"),
            record.get("Section"),
        )
        connection.execute(
            """
            INSERT INTO batch_students
                (batch_id, student_id, student_name, student_number, section, normalized_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                student_id,
                record.get("StudentName"),
                _as_text(record.get("StudentNumber")),
                record.get("Section"),
                record.get("NormalizedName") or normalize_name(record.get("StudentName")),
            ),
        )

    for row in result.result_rows:
        normalized_name = row.get("NormalizedName") or normalize_name(
            row.get("StudentName")
        )
        student_id = upsert_student(
            connection,
            normalized_name,
            row.get("StudentName"),
            row.get("StudentNumber"),
            row.get("Section"),
        )
        course_id = upsert_course(connection, row.get("Course"))
        connection.execute(
            """
            INSERT INTO grade_records
                (
                    batch_id, source_file_id, student_id, course_id, source_file,
                    section, course, student_number, student_name, normalized_name,
                    midterm_exam, midterm_grade, status, notes, raw_row_json
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                source_file_ids.get(row.get("SourceFile")),
                student_id,
                course_id,
                row.get("SourceFile"),
                row.get("Section"),
                row.get("Course"),
                _as_text(row.get("StudentNumber")),
                row.get("StudentName"),
                normalized_name,
                _as_text(row.get("MidtermExam")),
                row.get("MidtermGrade"),
                row.get("Status"),
                row.get("Notes"),
                row.get("RawRowJson"),
            ),
        )

    for issue in result.issues:
        connection.execute(
            """
            INSERT INTO ingest_issues
                (
                    batch_id, source_file_id, source_file, row_number, issue_type,
                    details, raw_student_number, raw_student_name,
                    raw_midterm_exam, raw_midterm_grade
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                source_file_ids.get(issue.get("SourceFile")),
                issue.get("SourceFile"),
                _as_text(issue.get("RowNumber")),
                issue.get("IssueType"),
                issue.get("Details"),
                _as_text(issue.get("RawStudentNumber")),
                _as_text(issue.get("RawStudentName")),
                _as_text(issue.get("RawMidtermExam")),
                _as_text(issue.get("RawMidtermGrade")),
            ),
        )

    connection.commit()
    return batch_id


def latest_batch_id(connection: sqlite3.Connection) -> Optional[int]:
    initialize_database(connection)
    row = connection.execute(
        "SELECT id FROM ingest_batches ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def list_batches(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    initialize_database(connection)
    rows = connection.execute(
        """
        SELECT id, label, created_at, passing_grade, files_processed,
               grade_count, issue_count
        FROM ingest_batches
        ORDER BY id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def load_batch_for_reports(
    connection: sqlite3.Connection, batch_id: Optional[int] = None
) -> Dict[str, List[Dict[str, Any]]]:
    initialize_database(connection)
    if batch_id is None:
        batch_id = latest_batch_id(connection)
    if batch_id is None:
        return {"masterlist_records": [], "result_rows": [], "issues": []}

    grade_rows = connection.execute(
        """
        SELECT source_file AS SourceFile, section AS Section, course AS Course,
               student_number AS StudentNumber, student_name AS StudentName,
               normalized_name AS NormalizedName, midterm_exam AS MidtermExam,
               midterm_grade AS MidtermGrade, status AS Status, notes AS Notes
        FROM grade_records
        WHERE batch_id = ?
        ORDER BY source_file, student_name
        """,
        (batch_id,),
    ).fetchall()

    issue_rows = connection.execute(
        """
        SELECT source_file AS SourceFile, row_number AS RowNumber,
               issue_type AS IssueType, details AS Details,
               raw_student_number AS RawStudentNumber,
               raw_student_name AS RawStudentName,
               raw_midterm_exam AS RawMidtermExam,
               raw_midterm_grade AS RawMidtermGrade
        FROM ingest_issues
        WHERE batch_id = ?
        ORDER BY source_file, id
        """,
        (batch_id,),
    ).fetchall()

    student_rows = connection.execute(
        """
        SELECT student_name AS StudentName, student_number AS StudentNumber,
               section AS Section, normalized_name AS NormalizedName
        FROM batch_students
        WHERE batch_id = ?
        ORDER BY section, student_name
        """,
        (batch_id,),
    ).fetchall()

    return {
        "masterlist_records": [dict(row) for row in student_rows],
        "result_rows": [dict(row) for row in grade_rows],
        "issues": [dict(row) for row in issue_rows],
    }


def list_grade_records(
    connection: sqlite3.Connection, batch_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    data = load_batch_for_reports(connection, batch_id)
    return data["result_rows"]


def list_issues(
    connection: sqlite3.Connection, batch_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    data = load_batch_for_reports(connection, batch_id)
    return data["issues"]
