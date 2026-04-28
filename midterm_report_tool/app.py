from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing

import streamlit as st

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


def selected_batch_id(batches):
    if not batches:
        return None
    labels = [
        f"#{batch['id']} - {batch['created_at']} - {batch['grade_count']} grades, {batch['issue_count']} issues"
        for batch in batches
    ]
    selected = st.selectbox("Batch", labels)
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
        batch_id = selected_batch_id(batches)
        grade_records = list_grade_records(connection, batch_id)
        issues = list_issues(connection, batch_id)

    if batch_id is None:
        st.info("No ingest batches yet.")
        return

    st.subheader("Issues")
    issue_type = st.selectbox(
        "Issue type",
        ["All"] + sorted({issue["IssueType"] for issue in issues if issue["IssueType"]}),
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
    section = st.selectbox("Section", sections)
    course = st.selectbox("Course", courses)
    status = st.selectbox("Status", statuses)

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
        batch_id = selected_batch_id(batches)

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


def main() -> None:
    st.set_page_config(page_title="Grade Compiler", layout="wide")
    st.title("Grade Compiler")

    ingest_tab, review_tab, export_tab = st.tabs(["Ingest", "Review", "Export"])
    with ingest_tab:
        run_ingest_panel()
    with review_tab:
        review_panel()
    with export_tab:
        export_panel()


if __name__ == "__main__":
    main()
