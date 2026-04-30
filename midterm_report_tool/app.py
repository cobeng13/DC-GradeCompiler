from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing

import streamlit as st

from db_editor import (
    apply_student_merge_batch,
    apply_student_merge,
    list_merge_history,
    list_students_for_editor,
    preview_student_merge,
    suggest_student_merges,
    undo_student_merge,
    update_student_identity,
)
from ingest import ingest_folder
from reports import generate_workbook_reports
from storage import (
    DEFAULT_DB_PATH,
    connect,
    list_batches,
    list_grade_records,
    list_issues,
    load_batch_for_reports,
    save_ingest_result,
)


DEFAULT_INPUT = Path("input/grades")
DEFAULT_MASTERLIST = Path("input/masterlist/masterlist.csv")
DEFAULT_OUTPUT = Path("output")


def write_uploaded_files(uploaded_files, target_folder: Path) -> None:
    target_folder.mkdir(parents=True, exist_ok=True)
    for uploaded_file in uploaded_files:
        (target_folder / uploaded_file.name).write_bytes(uploaded_file.getbuffer())


def selected_batch_id(batches, key: str):
    if not batches:
        return None
    labels = [
        f"#{batch['id']} - {batch['created_at']} - {batch['grade_count']} grades, {batch['issue_count']} issues"
        for batch in batches
    ]
    selected = st.selectbox("Batch", labels, key=key)
    index = labels.index(selected)
    return batches[index]["id"]


def run_ingest_panel() -> None:
    st.header("Ingest")
    mode = st.radio("Source", ["Use input folder", "Upload workbooks"], horizontal=True)
    passing_grade = st.number_input("Passing grade", value=75.0, step=1.0)
    batch_label = st.text_input("Batch label", value="")
    masterlist_path = Path(
        st.text_input("Masterlist path", value=str(DEFAULT_MASTERLIST))
    )

    if mode == "Use input folder":
        input_folder = Path(st.text_input("Input folder", value=str(DEFAULT_INPUT)))
        if st.button("Run ingest", type="primary"):
            result = ingest_folder(input_folder, masterlist_path, passing_grade)
            with closing(connect(DEFAULT_DB_PATH)) as connection:
                batch_id = save_ingest_result(connection, result, batch_label)
            st.success(f"Saved batch #{batch_id}")
            st.write(
                {
                    "files_processed": result.files_processed,
                    "grade_records": len(result.result_rows),
                    "issues": len(result.issues),
                }
            )
        return

    uploaded_files = st.file_uploader(
        "Workbooks", type=["xlsx", "xlsm"], accept_multiple_files=True
    )
    if st.button("Upload and ingest", type="primary", disabled=not uploaded_files):
        with TemporaryDirectory() as temp_dir:
            temp_folder = Path(temp_dir)
            write_uploaded_files(uploaded_files, temp_folder)
            result = ingest_folder(temp_folder, masterlist_path, passing_grade)
            with closing(connect(DEFAULT_DB_PATH)) as connection:
                batch_id = save_ingest_result(connection, result, batch_label)
        st.success(f"Saved batch #{batch_id}")
        st.write(
            {
                "files_processed": result.files_processed,
                "grade_records": len(result.result_rows),
                "issues": len(result.issues),
            }
        )


def review_panel() -> None:
    st.header("Review")
    with closing(connect(DEFAULT_DB_PATH)) as connection:
        batches = list_batches(connection)
        batch_id = selected_batch_id(batches, key="review_batch")
        grade_records = list_grade_records(connection, batch_id)
        issues = list_issues(connection, batch_id)

    if batch_id is None:
        st.info("No ingest batches yet.")
        return

    st.subheader("Issues")
    issue_type = st.selectbox(
        "Issue type",
        ["All"] + sorted({issue["IssueType"] for issue in issues if issue["IssueType"]}),
        key="review_issue_type",
    )
    visible_issues = issues
    if issue_type != "All":
        visible_issues = [
            issue for issue in visible_issues if issue["IssueType"] == issue_type
        ]
    st.dataframe(visible_issues, use_container_width=True, hide_index=True)

    st.subheader("Grade Records")
    sections = ["All"] + sorted(
        {row["Section"] for row in grade_records if row.get("Section")}
    )
    courses = ["All"] + sorted(
        {row["Course"] for row in grade_records if row.get("Course")}
    )
    statuses = ["All", "Passed", "Fail"]
    section = st.selectbox("Section", sections, key="review_section")
    course = st.selectbox("Course", courses, key="review_course")
    status = st.selectbox("Status", statuses, key="review_status")

    visible_records = grade_records
    if section != "All":
        visible_records = [
            row for row in visible_records if row.get("Section") == section
        ]
    if course != "All":
        visible_records = [row for row in visible_records if row.get("Course") == course]
    if status != "All":
        visible_records = [
            row for row in visible_records if row.get("Status") == status
        ]
    st.dataframe(visible_records, use_container_width=True, hide_index=True)


def export_panel() -> None:
    st.header("Export")
    with closing(connect(DEFAULT_DB_PATH)) as connection:
        batches = list_batches(connection)
        batch_id = selected_batch_id(batches, key="export_batch")

    if batch_id is None:
        st.info("No ingest batches yet.")
        return

    output_folder = Path(st.text_input("Output folder", value=str(DEFAULT_OUTPUT)))
    if st.button("Generate reports", type="primary"):
        output_file = output_folder / "passed_midterm_report.xlsx"
        pass_fail_output_file = output_folder / "midterm_exam_pass_fail_report.xlsx"
        grade_output_file = output_folder / "midterm_grade_report.xlsx"
        with closing(connect(DEFAULT_DB_PATH)) as connection:
            report_data = load_batch_for_reports(connection, batch_id)

        generate_workbook_reports(
            output_file,
            pass_fail_output_file,
            grade_output_file,
            report_data["masterlist_records"],
            report_data["result_rows"],
            report_data["issues"],
        )
        st.success("Reports generated")
        st.write(str(output_file.resolve()))
        st.write(str(pass_fail_output_file.resolve()))
        st.write(str(grade_output_file.resolve()))


def _student_option_label(student) -> str:
    return (
        f"#{student['StudentId']} - {student.get('StudentName') or ''} "
        f"({student.get('StudentNumber') or 'no ID'}, {student.get('Section') or 'no section'})"
    )


def _preview_student_label(student) -> str:
    return (
        f"#{student['id']} - {student.get('display_name') or ''} "
        f"({student.get('student_number') or 'no ID'}, {student.get('section') or 'no section'})"
    )


def _suggestion_select_index(suggestion_labels) -> int:
    requested_index = st.session_state.pop("merge_suggestion_next_index", None)
    if requested_index is not None:
        st.session_state.pop("merge_suggestion", None)
        st.session_state.pop("suggested_merge_canonical", None)
        return min(int(requested_index), len(suggestion_labels) - 1)

    selected_label = st.session_state.get("merge_suggestion")
    if selected_label in suggestion_labels:
        return suggestion_labels.index(selected_label)
    return 0


def _suggestion_review_rows(suggestions):
    rows = []
    for index, suggestion in enumerate(suggestions):
        rows.append(
            {
                "Approve": False,
                "MergeTo": suggestion.get("MergeTo") or "",
                "MergeFrom": suggestion.get("MergeFrom") or "",
                "Reason": suggestion.get("Reasons") or "",
                "Confidence": suggestion.get("Confidence") or 0,
                "Conflicts": "Yes" if suggestion.get("HasConflicts") else "No",
                "Index": index,
            }
        )
    return rows


def _show_merge_preview(student_ids, key_prefix: str):
    with closing(connect(DEFAULT_DB_PATH)) as connection:
        initial_preview = preview_student_merge(connection, student_ids)

    current_student_ids = tuple(sorted(int(student_id) for student_id in student_ids))
    student_labels = {
        _preview_student_label(student): student["id"]
        for student in initial_preview["students"]
    }
    default_label = next(
        label
        for label, student_id in student_labels.items()
        if student_id == initial_preview["canonical_student"]["id"]
    )
    canonical_key = (
        f"{key_prefix}_canonical_"
        + "_".join(str(student_id) for student_id in current_student_ids)
    )
    selected_label = st.selectbox(
        "Merge to",
        list(student_labels),
        index=list(student_labels).index(default_label),
        key=canonical_key,
    )
    canonical_student_id = student_labels[selected_label]

    with closing(connect(DEFAULT_DB_PATH)) as connection:
        preview = preview_student_merge(
            connection, student_ids, canonical_student_id=canonical_student_id
        )

    canonical = preview["canonical_student"]
    fields = preview["canonical_fields"]
    left, middle, right = st.columns(3)
    left.metric("Canonical ID", canonical["id"])
    middle.metric("Grade rows", preview["affected_grade_rows"])
    right.metric("Batch student rows", preview["affected_batch_student_rows"])
    st.caption(
        f"Canonical identity: {fields['display_name']} | "
        f"{fields['student_number'] or 'no ID'} | {fields['section'] or 'no section'}"
    )
    st.dataframe(preview["students"], use_container_width=True, hide_index=True)

    if preview["conflicts"]:
        st.error("This merge has duplicate grade rows for the same batch/course.")
        st.dataframe(preview["conflicts"], use_container_width=True, hide_index=True)
        return False, canonical_student_id
    return True, canonical_student_id


def database_editor_panel() -> None:
    st.header("Database Editor")
    with closing(connect(DEFAULT_DB_PATH)) as connection:
        students = list_students_for_editor(connection)
        suggestions = suggest_student_merges(connection)
        history = list_merge_history(connection)

    if not students:
        st.info("No students found. Run an ingest first.")
        return

    suggestions_tab, browse_tab, history_tab = st.tabs(
        ["Suggestions", "Browse Students", "History"]
    )

    with suggestions_tab:
        st.subheader("Suggested Merges")
        merge_notice = st.session_state.pop("suggested_merge_notice", None)
        if merge_notice:
            st.success(merge_notice)
        if not suggestions:
            st.info("No likely merge candidates found.")
        else:
            review_rows = _suggestion_review_rows(suggestions)
            review_key_version = st.session_state.get("suggested_merge_review_version", 0)
            edited_rows = st.data_editor(
                review_rows,
                use_container_width=True,
                hide_index=True,
                key=f"suggested_merge_review_{review_key_version}",
                disabled=["MergeTo", "MergeFrom", "Reason", "Confidence", "Conflicts", "Index"],
                column_config={
                    "Approve": st.column_config.CheckboxColumn("Approve"),
                    "MergeTo": st.column_config.TextColumn("Merge to"),
                    "MergeFrom": st.column_config.TextColumn("Merge from"),
                    "Reason": st.column_config.TextColumn("Reason"),
                    "Confidence": st.column_config.NumberColumn("Confidence"),
                    "Conflicts": st.column_config.TextColumn("Conflicts"),
                    "Index": None,
                },
            )
            selected_candidates = [
                suggestions[int(row["Index"])]
                for row in edited_rows
                if row.get("Approve")
            ]
            selected_count = len(selected_candidates)
            if st.button(
                f"Approve selected ({selected_count})",
                type="primary",
                disabled=selected_count == 0,
                key="apply_selected_suggested_merges",
            ):
                with closing(connect(DEFAULT_DB_PATH)) as connection:
                    batch_result = apply_student_merge_batch(
                        connection, selected_candidates
                    )
                st.session_state["suggested_merge_review_version"] = (
                    review_key_version + 1
                )
                st.session_state["suggested_merge_notice"] = (
                    f"Applied {batch_result['AppliedCount']} merges. "
                    f"Skipped {batch_result['SkippedCount']} rows."
                )
                st.rerun()

    with browse_tab:
        st.subheader("Students")
        search_text = st.text_input("Search", key="student_search").strip().lower()
        visible_students = students
        if search_text:
            visible_students = [
                student
                for student in visible_students
                if search_text in str(student.get("StudentName") or "").lower()
                or search_text in str(student.get("StudentNumber") or "").lower()
                or search_text in str(student.get("Section") or "").lower()
            ]
        st.dataframe(visible_students, use_container_width=True, hide_index=True)

        st.subheader("Manual Merge")
        options = [_student_option_label(student) for student in students]
        selected_options = st.multiselect(
            "Students to merge",
            options,
            key="manual_merge_students",
        )
        option_to_student_id = {
            _student_option_label(student): student["StudentId"] for student in students
        }
        selected_ids = [option_to_student_id[option] for option in selected_options]
        can_merge = len(selected_ids) >= 2
        canonical_student_id = None
        if can_merge:
            try:
                can_merge, canonical_student_id = _show_merge_preview(
                    selected_ids, key_prefix="manual_merge"
                )
            except ValueError as exc:
                st.error(str(exc))
                can_merge = False
        if st.button(
            "Apply manual merge",
            type="primary",
            disabled=not can_merge,
            key="apply_manual_merge",
        ):
            try:
                with closing(connect(DEFAULT_DB_PATH)) as connection:
                    merge_id = apply_student_merge(
                        connection,
                        selected_ids,
                        canonical_student_id=canonical_student_id,
                    )
                st.success(f"Applied merge #{merge_id}")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        st.subheader("Edit Identity")
        edit_label = st.selectbox("Student", options, key="edit_student")
        edit_student = next(
            student
            for student in students
            if student["StudentId"] == option_to_student_id[edit_label]
        )
        with st.form("identity_edit_form"):
            display_name = st.text_input(
                "Name", value=edit_student.get("StudentName") or ""
            )
            student_number = st.text_input(
                "Student number", value=edit_student.get("StudentNumber") or ""
            )
            section = st.text_input("Section", value=edit_student.get("Section") or "")
            submitted = st.form_submit_button("Save identity")
        if submitted:
            try:
                with closing(connect(DEFAULT_DB_PATH)) as connection:
                    update_student_identity(
                        connection,
                        edit_student["StudentId"],
                        display_name,
                        student_number,
                        section,
                    )
                st.success("Identity updated")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with history_tab:
        st.subheader("Merge History")
        st.dataframe(history, use_container_width=True, hide_index=True)
        applied_history = [item for item in history if item["Status"] == "applied"]
        if applied_history:
            labels = [
                f"#{item['MergeId']} - {item['CreatedAt']} - {item.get('CanonicalName') or item['CanonicalStudentId']}"
                for item in applied_history
            ]
            selected = st.selectbox("Merge to undo", labels, key="undo_merge")
            selected_merge = applied_history[labels.index(selected)]
            if st.button("Undo merge", key="undo_merge_button"):
                try:
                    with closing(connect(DEFAULT_DB_PATH)) as connection:
                        undo_student_merge(connection, selected_merge["MergeId"])
                    st.success(f"Reverted merge #{selected_merge['MergeId']}")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def main() -> None:
    st.set_page_config(page_title="Grade Compiler", layout="wide")
    st.title("Grade Compiler")

    ingest_tab, review_tab, export_tab, database_tab = st.tabs(
        ["Ingest", "Review", "Export", "Database Editor"]
    )
    with ingest_tab:
        run_ingest_panel()
    with review_tab:
        review_panel()
    with export_tab:
        export_panel()
    with database_tab:
        database_editor_panel()


if __name__ == "__main__":
    main()
