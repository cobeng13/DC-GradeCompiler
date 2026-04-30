# Midterm Report Tool

This tool ingests Excel grading sheets into a local SQLite database and generates
midterm reports from the stored data. It keeps issue rows for files that do not
match the expected template, so faculty uploads can be reviewed without crashing
the workflow.

## 1. Where to place files

Place all grading sheets directly in:

```text
input/grades/
```

The tool reads `.xlsx` and `.xlsm` files from that folder only. It does not
scan subfolders or modify the original files.

Place the student masterlist here:

```text
input/masterlist/masterlist.csv
```

The masterlist should contain these columns:

```text
Name
StudentNumber or ClassNumber
```

The tool uses the masterlist as the only trusted source for student numbers.
Student numbers typed into grading sheets are ignored because faculty files may
contain incorrect IDs.

## 2. Expected filename pattern

Use this filename pattern when possible:

```text
Section_Course.xlsx
Section_Course.xlsm
```

Examples:

```text
2A_OrgMedChem.xlsm
2B_Biochemistry.xlsx
```

The report parses:

- `Section` from the text before the first underscore.
- `Course` from the text after the first underscore, excluding the file extension.

If a filename does not match this pattern, the report leaves `Section` and `Course` blank and adds a note.

## 3. How to run the CLI

Install dependencies:

```bash
pip install -r requirements.txt
```

Run with defaults:

```bash
python main.py
```

Default settings:

- Input folder: `input/grades`
- Masterlist file: `input/masterlist/masterlist.csv`
- Output file: `output/passed_midterm_report.xlsx`
- Pass/fail matrix file: `output/midterm_exam_pass_fail_report.xlsx`
- Midterm grade matrix file: `output/midterm_grade_report.xlsx`
- Passing grade: `75`
- SQLite database: `data/grade_compiler.sqlite3`

Run with custom paths or passing grade:

```bash
python main.py --input input/grades --masterlist input/masterlist/masterlist.csv --output output/passed_midterm_report.xlsx --pass-fail-output output/midterm_exam_pass_fail_report.xlsx --grade-output output/midterm_grade_report.xlsx --passing-grade 75
```

Export reports from the latest saved database batch without re-reading Excel:

```bash
python main.py --export-only
```

Export a specific batch:

```bash
python main.py --export-only --batch-id 3
```

## 4. How to run the UI

Install dependencies, then run:

```bash
streamlit run app.py
```

The UI has three tabs:

- `Ingest`: run an ingest from the input folder or uploaded workbooks.
- `Review`: inspect batches, normalized grade records, and issues.
- `Export`: generate the Excel reports from a selected batch.
- `Database Editor`: review suggested duplicate student entries, manually merge
  entries, edit student identity fields, and undo applied merges.

## 5. How to reset test state

To preview generated files that would be removed:

```bash
python reset_test_state.py --dry-run
```

To reset generated test/run state without deleting grading inputs or the masterlist:

```bash
python reset_test_state.py --yes
```

This removes the local SQLite database, generated reports, Streamlit logs, test
scratch folders, and Python caches. It preserves files under `input/grades/` and
`input/masterlist/` by default.

## 6. How passing is computed

The tool detects columns by Row 1 headers using flexible aliases.

Required processable columns:

- `StudentName`
- `MidtermExam`
- `MidtermGrade`

`StudentNumber` may be detected when present, but it is not trusted. Passed rows
are still included, and the tool fills the canonical student number only from
`input/masterlist/masterlist.csv` by matching `StudentName` to masterlist `Name`.
If no masterlist match is found, the student number is left blank and a note is
added to the row.

Name matching is normalized exact matching:

- Case-insensitive.
- Ignores punctuation and extra spaces.
- Does not use fuzzy matching.

A student is included in the `PassedStudents` sheet when:

```text
MidtermGrade >= passing grade
```

By default, the passing grade is `75`.

## 7. Midterm Exam Pass/Fail Report

The tool also creates two matrix reports:

```text
output/midterm_exam_pass_fail_report.xlsx
output/midterm_grade_report.xlsx
```

These workbooks use the same matrix layout:

- One sheet per year level, such as `Year1`, `Year2`, and `Year3`.
- Year level is inferred from the first number in the section, such as `1A` or `2B`.
- Students with no known section are placed in `Unassigned`.
- Rows come from the masterlist, plus any students found in grading sheets when the masterlist is missing or incomplete.
- Near-duplicate student names are merged when they share a section, the leading
  name token, and at least 10 ordered matching characters covering most of the
  shorter name. This handles abbreviated names and minor spelling variants while
  avoiding merges across different nonblank sections.
- Columns are `Name`, `Section`, then one column per course found from grading filenames.
- Pass/fail course cells contain `Passed`, `Fail`, or blank when no result exists.
- Midterm grade course cells contain the numeric `MidtermGrade`, or blank when no result exists.

## 8. What the Issues sheet means

The `Issues` sheet records rows or files that need attention, including:

- Workbooks that could not be opened.
- Sheets missing required columns.
- Files with no processable sheet.
- Blank or non-numeric `MidtermGrade` values.
- Missing `StudentNumber` columns.
- Missing or invalid `masterlist.csv`.
- Missing input files or input folder.
- Duplicate student/course rows in one batch.

The output workbook contains:

- `PassedStudents`: all passing students and their midterm grades.
- `Issues`: rows and files that could not be processed cleanly.

The separate matrix workbooks contain one sheet per year level.

## 9. Database-backed workflow

Each run creates an ingest batch. The database stores:

- Source files and whether they had processable sheets.
- Students and courses discovered during ingest.
- Normalized grade records, including the standard grading sheet fields such as
  `MQ1`-`MQ10`, `MA1`-`MA10`, midterm component totals, final component totals,
  `FinalGrade`, and `Interpretation`.
- Issues for rows/files that need review.

Reports are generated from the database, not directly from Excel, after ingest.

## 10. Database Editor

The Database Editor works on the local SQLite database and is intended for
cleanup after ingest. It suggests merge candidates using matching student
numbers, compatible-section name variants, and existing name normalization.

Merges are global across the database. The tool picks a canonical student by
preferring a nonblank student number, then a nonblank section, then the longest
display name. It updates linked grade and batch rows so future review and export
views use the canonical identity.

If two selected entries have grade rows for the same batch and course, the merge
is blocked and the conflicting rows are shown for review. Each applied merge is
recorded in merge history and can be undone from the UI.
