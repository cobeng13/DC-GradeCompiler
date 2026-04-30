import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ingest import is_blank, normalize_name
from reports import names_are_ordered_merge_match, sections_are_merge_compatible
from storage import initialize_database


def _dicts(rows) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _student_rows(connection: sqlite3.Connection, student_ids: List[int]) -> List[Dict[str, Any]]:
    if not student_ids:
        return []
    placeholders = ",".join("?" for _ in student_ids)
    rows = connection.execute(
        f"""
        SELECT id, display_name, student_number, section, normalized_name
        FROM students
        WHERE id IN ({placeholders})
        ORDER BY id
        """,
        tuple(student_ids),
    ).fetchall()
    return _dicts(rows)


def list_students_for_editor(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    initialize_database(connection)
    rows = connection.execute(
        """
        SELECT s.id AS StudentId,
               s.display_name AS StudentName,
               s.student_number AS StudentNumber,
               s.section AS Section,
               s.normalized_name AS NormalizedName,
               COUNT(DISTINCT bs.id) AS BatchStudentRows,
               COUNT(DISTINCT gr.id) AS GradeRows
        FROM students s
        LEFT JOIN batch_students bs ON bs.student_id = s.id
        LEFT JOIN grade_records gr ON gr.student_id = s.id
        GROUP BY s.id
        ORDER BY s.section, s.display_name, s.id
        """
    ).fetchall()
    return _dicts(rows)


def _canonical_sort_key(student: Dict[str, Any]) -> Tuple[int, int, int, int]:
    return (
        0 if not is_blank(student.get("student_number")) else 1,
        0 if not is_blank(student.get("section")) else 1,
        -len(_as_text(student.get("display_name"))),
        int(student["id"]),
    )


def choose_canonical_student(students: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not students:
        raise ValueError("No students selected.")
    return sorted(students, key=_canonical_sort_key)[0]


def _first_nonblank(students: List[Dict[str, Any]], field: str) -> str:
    for student in students:
        value = student.get(field)
        if not is_blank(value):
            return _as_text(value)
    return ""


def _canonical_fields(students: List[Dict[str, Any]], canonical: Dict[str, Any]) -> Dict[str, str]:
    ordered = [canonical] + [student for student in students if student["id"] != canonical["id"]]
    display_name = _first_nonblank(ordered, "display_name")
    student_number = _first_nonblank(ordered, "student_number")
    section = _first_nonblank(ordered, "section")
    normalized_name = normalize_name(display_name)
    if not normalized_name:
        normalized_name = _as_text(canonical.get("normalized_name"))
    return {
        "display_name": display_name,
        "student_number": student_number,
        "section": section,
        "normalized_name": normalized_name,
    }


def _suggestion_key(student_ids: List[int]) -> Tuple[int, ...]:
    return tuple(sorted(set(int(student_id) for student_id in student_ids)))


def _display_student(student: Dict[str, Any]) -> str:
    return (
        f"{student.get('display_name') or ''} "
        f"({student.get('student_number') or 'no ID'}, {student.get('section') or 'no section'})"
    ).strip()


def _shared_nonfamily_tokens(left: Dict[str, Any], right: Dict[str, Any]) -> set[str]:
    left_tokens = normalize_name(left.get("normalized_name") or left.get("display_name")).split()
    right_tokens = normalize_name(right.get("normalized_name") or right.get("display_name")).split()
    return set(left_tokens[1:]) & set(right_tokens[1:])


def _is_short_name_subset_candidate(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_tokens = normalize_name(left.get("normalized_name") or left.get("display_name")).split()
    right_tokens = normalize_name(right.get("normalized_name") or right.get("display_name")).split()
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    if len(left_tokens) == len(right_tokens):
        return False

    shorter_tokens, longer_tokens = sorted(
        [left_tokens, right_tokens],
        key=lambda tokens: len(tokens),
    )
    return longer_tokens[: len(shorter_tokens)] == shorter_tokens


def _applied_merge_keys(connection: sqlite3.Connection) -> set[Tuple[int, ...]]:
    rows = connection.execute(
        """
        SELECT merged_student_ids_json
        FROM student_merge_history
        WHERE status = 'applied'
        """
    ).fetchall()
    keys = set()
    for row in rows:
        try:
            student_ids = json.loads(row["merged_student_ids_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        keys.add(_suggestion_key(student_ids))
    return keys


def suggest_student_merges(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    initialize_database(connection)
    students = _student_rows(
        connection,
        [row["id"] for row in connection.execute("SELECT id FROM students").fetchall()],
    )
    applied_merge_keys = _applied_merge_keys(connection)
    suggestions: Dict[Tuple[int, ...], Dict[str, Any]] = {}

    for index, left in enumerate(students):
        for right in students[index + 1 :]:
            reasons = []
            if (
                not is_blank(left.get("student_number"))
                and left.get("student_number") == right.get("student_number")
            ):
                reasons.append("Matching student number")
            if (
                not is_blank(left.get("normalized_name"))
                and left.get("normalized_name") == right.get("normalized_name")
            ):
                reasons.append("Exact normalized name")
            if sections_are_merge_compatible(left.get("section"), right.get("section")):
                if names_are_ordered_merge_match(
                    left.get("normalized_name"), right.get("normalized_name")
                ):
                    reasons.append("Close typo/name variant")
            if _is_short_name_subset_candidate(left, right):
                reasons.append("Short-name subset")
                if not sections_are_merge_compatible(left.get("section"), right.get("section")):
                    reasons.append("Section mismatch")

            if not reasons:
                continue

            key = _suggestion_key([left["id"], right["id"]])
            if key in applied_merge_keys:
                continue

            preview = preview_student_merge(connection, list(key))
            confidence = 70
            if "Section mismatch" in reasons:
                confidence = 60
            if "Close typo/name variant" in reasons:
                confidence = 85
            if "Exact normalized name" in reasons:
                confidence = max(confidence, 90)
            if "Matching student number" in reasons:
                confidence = max(confidence, 95)
            canonical_id = preview["canonical_student"]["id"]
            merge_to = next(
                student for student in preview["students"] if student["id"] == canonical_id
            )
            merge_from = [
                student for student in preview["students"] if student["id"] != canonical_id
            ]
            suggestions[key] = {
                "StudentIds": list(key),
                "CanonicalStudentId": canonical_id,
                "MergeTo": _display_student(merge_to),
                "MergeFrom": " | ".join(_display_student(student) for student in merge_from),
                "Reasons": ", ".join(reasons),
                "Confidence": confidence,
                "HasConflicts": bool(preview["conflicts"]),
                "Students": preview["students"],
            }

    return sorted(
        suggestions.values(),
        key=lambda item: (item["HasConflicts"], -item["Confidence"], item["StudentIds"]),
    )


def apply_student_merge_batch(
    connection: sqlite3.Connection, candidates: List[Dict[str, Any]]
) -> Dict[str, Any]:
    applied_merge_ids: List[int] = []
    skipped: List[Dict[str, Any]] = []

    for candidate in candidates:
        student_ids = candidate.get("StudentIds") or []
        canonical_student_id = candidate.get("CanonicalStudentId")
        try:
            preview = preview_student_merge(connection, student_ids, canonical_student_id)
            if preview["conflicts"]:
                skipped.append(
                    {
                        "StudentIds": student_ids,
                        "Reason": "Conflicting grade rows",
                    }
                )
                continue
            applied_merge_ids.append(
                apply_student_merge(connection, student_ids, canonical_student_id)
            )
        except ValueError as exc:
            skipped.append({"StudentIds": student_ids, "Reason": str(exc)})

    return {
        "AppliedCount": len(applied_merge_ids),
        "AppliedMergeIds": applied_merge_ids,
        "SkippedCount": len(skipped),
        "Skipped": skipped,
    }


def _grade_snapshot(connection: sqlite3.Connection, student_ids: List[int]) -> List[Dict[str, Any]]:
    placeholders = ",".join("?" for _ in student_ids)
    rows = connection.execute(
        f"""
        SELECT id, student_id, student_name, student_number, section, normalized_name
        FROM grade_records
        WHERE student_id IN ({placeholders})
        ORDER BY id
        """,
        tuple(student_ids),
    ).fetchall()
    return _dicts(rows)


def _batch_student_snapshot(
    connection: sqlite3.Connection, student_ids: List[int]
) -> List[Dict[str, Any]]:
    placeholders = ",".join("?" for _ in student_ids)
    rows = connection.execute(
        f"""
        SELECT id, student_id, student_name, student_number, section, normalized_name
        FROM batch_students
        WHERE student_id IN ({placeholders})
        ORDER BY id
        """,
        tuple(student_ids),
    ).fetchall()
    return _dicts(rows)


def _snapshot(connection: sqlite3.Connection, student_ids: List[int]) -> Dict[str, Any]:
    return {
        "students": _student_rows(connection, student_ids),
        "grade_records": _grade_snapshot(connection, student_ids),
        "batch_students": _batch_student_snapshot(connection, student_ids),
    }


def find_merge_conflicts(
    connection: sqlite3.Connection, student_ids: List[int]
) -> List[Dict[str, Any]]:
    if len(set(student_ids)) < 2:
        return []
    placeholders = ",".join("?" for _ in student_ids)
    rows = connection.execute(
        f"""
        SELECT batch_id AS BatchId,
               COALESCE(course, '') AS Course,
               COUNT(*) AS GradeRows,
               GROUP_CONCAT(id) AS GradeRecordIds,
               GROUP_CONCAT(student_name, ' | ') AS StudentNames
        FROM grade_records
        WHERE student_id IN ({placeholders})
        GROUP BY batch_id, COALESCE(course, '')
        HAVING COUNT(*) > 1
        ORDER BY batch_id, Course
        """,
        tuple(student_ids),
    ).fetchall()
    return _dicts(rows)


def _canonical_by_id(
    students: List[Dict[str, Any]], canonical_student_id: Optional[int]
) -> Dict[str, Any]:
    if canonical_student_id is None:
        return choose_canonical_student(students)
    for student in students:
        if int(student["id"]) == int(canonical_student_id):
            return student
    raise ValueError("Canonical student must be one of the selected students.")


def preview_student_merge(
    connection: sqlite3.Connection,
    student_ids: List[int],
    canonical_student_id: Optional[int] = None,
) -> Dict[str, Any]:
    initialize_database(connection)
    unique_ids = list(_suggestion_key(student_ids))
    students = _student_rows(connection, unique_ids)
    if len(students) != len(unique_ids):
        raise ValueError("One or more selected students do not exist.")
    canonical = _canonical_by_id(students, canonical_student_id)
    fields = _canonical_fields(students, canonical)
    return {
        "students": students,
        "canonical_student": canonical,
        "canonical_fields": fields,
        "conflicts": find_merge_conflicts(connection, unique_ids),
        "affected_grade_rows": len(_grade_snapshot(connection, unique_ids)),
        "affected_batch_student_rows": len(_batch_student_snapshot(connection, unique_ids)),
    }


def apply_student_merge(
    connection: sqlite3.Connection,
    student_ids: List[int],
    canonical_student_id: Optional[int] = None,
) -> int:
    initialize_database(connection)
    unique_ids = list(_suggestion_key(student_ids))
    if len(unique_ids) < 2:
        raise ValueError("Select at least two students to merge.")

    preview = preview_student_merge(connection, unique_ids, canonical_student_id)
    if preview["conflicts"]:
        raise ValueError("Merge has conflicting grade rows and was not applied.")

    students = preview["students"]
    canonical = preview["canonical_student"]
    fields = preview["canonical_fields"]
    canonical_id = int(canonical["id"])
    before = _snapshot(connection, unique_ids)

    existing = connection.execute(
        """
        SELECT id FROM students
        WHERE normalized_name = ? AND id != ?
        """,
        (fields["normalized_name"], canonical_id),
    ).fetchone()
    if existing and int(existing["id"]) not in unique_ids:
        raise ValueError("Canonical normalized name already belongs to another student.")

    connection.execute("BEGIN")
    try:
        connection.execute(
            """
            UPDATE students
            SET display_name = ?, student_number = ?, section = ?, normalized_name = ?
            WHERE id = ?
            """,
            (
                fields["display_name"],
                fields["student_number"],
                fields["section"],
                fields["normalized_name"],
                canonical_id,
            ),
        )
        placeholders = ",".join("?" for _ in unique_ids)
        connection.execute(
            f"""
            UPDATE grade_records
            SET student_id = ?,
                student_name = ?,
                student_number = ?,
                section = ?,
                normalized_name = ?
            WHERE student_id IN ({placeholders})
            """,
            (
                canonical_id,
                fields["display_name"],
                fields["student_number"],
                fields["section"],
                fields["normalized_name"],
                *unique_ids,
            ),
        )
        connection.execute(
            f"""
            UPDATE batch_students
            SET student_id = ?,
                student_name = ?,
                student_number = ?,
                section = ?,
                normalized_name = ?
            WHERE student_id IN ({placeholders})
            """,
            (
                canonical_id,
                fields["display_name"],
                fields["student_number"],
                fields["section"],
                fields["normalized_name"],
                *unique_ids,
            ),
        )

        after = _snapshot(connection, unique_ids)
        cursor = connection.execute(
            """
            INSERT INTO student_merge_history
                (
                    created_at, reverted_at, status, canonical_student_id,
                    merged_student_ids_json, before_json, after_json
                )
            VALUES (?, NULL, 'applied', ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                canonical_id,
                json.dumps(unique_ids),
                json.dumps(before, default=str),
                json.dumps(after, default=str),
            ),
        )
        merge_id = int(cursor.lastrowid)
        for student in students:
            connection.execute(
                """
                INSERT INTO student_merge_members
                    (
                        merge_id, student_id, display_name, student_number,
                        section, normalized_name, was_canonical
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    merge_id,
                    student["id"],
                    student.get("display_name"),
                    student.get("student_number"),
                    student.get("section"),
                    student.get("normalized_name"),
                    1 if int(student["id"]) == canonical_id else 0,
                ),
            )
        connection.commit()
        return merge_id
    except Exception:
        connection.rollback()
        raise


def list_merge_history(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    initialize_database(connection)
    rows = connection.execute(
        """
        SELECT h.id AS MergeId,
               h.created_at AS CreatedAt,
               h.reverted_at AS RevertedAt,
               h.status AS Status,
               h.canonical_student_id AS CanonicalStudentId,
               s.display_name AS CanonicalName,
               h.merged_student_ids_json AS StudentIds
        FROM student_merge_history h
        LEFT JOIN students s ON s.id = h.canonical_student_id
        ORDER BY h.id DESC
        """
    ).fetchall()
    return _dicts(rows)


def undo_student_merge(connection: sqlite3.Connection, merge_id: int) -> None:
    initialize_database(connection)
    history = connection.execute(
        "SELECT status, before_json FROM student_merge_history WHERE id = ?",
        (merge_id,),
    ).fetchone()
    if history is None:
        raise ValueError("Merge history record does not exist.")
    if history["status"] != "applied":
        raise ValueError("Merge has already been reverted.")

    before = json.loads(history["before_json"])
    connection.execute("BEGIN")
    try:
        for student in before["students"]:
            connection.execute(
                """
                UPDATE students
                SET display_name = ?, student_number = ?, section = ?, normalized_name = ?
                WHERE id = ?
                """,
                (
                    student.get("display_name"),
                    student.get("student_number"),
                    student.get("section"),
                    student.get("normalized_name"),
                    student["id"],
                ),
            )
        for row in before["grade_records"]:
            connection.execute(
                """
                UPDATE grade_records
                SET student_id = ?, student_name = ?, student_number = ?,
                    section = ?, normalized_name = ?
                WHERE id = ?
                """,
                (
                    row.get("student_id"),
                    row.get("student_name"),
                    row.get("student_number"),
                    row.get("section"),
                    row.get("normalized_name"),
                    row["id"],
                ),
            )
        for row in before["batch_students"]:
            connection.execute(
                """
                UPDATE batch_students
                SET student_id = ?, student_name = ?, student_number = ?,
                    section = ?, normalized_name = ?
                WHERE id = ?
                """,
                (
                    row.get("student_id"),
                    row.get("student_name"),
                    row.get("student_number"),
                    row.get("section"),
                    row.get("normalized_name"),
                    row["id"],
                ),
            )
        connection.execute(
            """
            UPDATE student_merge_history
            SET status = 'reverted', reverted_at = ?
            WHERE id = ?
            """,
            (datetime.now().isoformat(timespec="seconds"), merge_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def update_student_identity(
    connection: sqlite3.Connection,
    student_id: int,
    display_name: str,
    student_number: str,
    section: str,
) -> None:
    initialize_database(connection)
    normalized_name = normalize_name(display_name)
    if not normalized_name:
        raise ValueError("Student name cannot be blank.")
    existing = connection.execute(
        "SELECT id FROM students WHERE normalized_name = ? AND id != ?",
        (normalized_name, student_id),
    ).fetchone()
    if existing:
        raise ValueError("Another student already has this normalized name.")

    connection.execute("BEGIN")
    try:
        connection.execute(
            """
            UPDATE students
            SET display_name = ?, student_number = ?, section = ?, normalized_name = ?
            WHERE id = ?
            """,
            (display_name, student_number, section, normalized_name, student_id),
        )
        connection.execute(
            """
            UPDATE grade_records
            SET student_name = ?, student_number = ?, section = ?, normalized_name = ?
            WHERE student_id = ?
            """,
            (display_name, student_number, section, normalized_name, student_id),
        )
        connection.execute(
            """
            UPDATE batch_students
            SET student_name = ?, student_number = ?, section = ?, normalized_name = ?
            WHERE student_id = ?
            """,
            (display_name, student_number, section, normalized_name, student_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
