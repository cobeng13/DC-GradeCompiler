# Midterm Report Tool

This CLI tool reads standard Excel grading sheets and generates one report of students who passed the midterm.

## 1. Where to place files

Place all grading sheets in:

```text
input/grades/
```

The tool reads `.xlsx` and `.xlsm` files. It does not modify the original files.

Place the student masterlist here:

```text
input/masterlist/masterlist.csv
```

The masterlist should contain these columns:

```text
Name
StudentNumber or ClassNumber
```

The tool uses the masterlist only to fill missing or blank student numbers in the grading sheets.

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

## 3. How to run the tool

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
- Passing grade: `75`

Run with custom paths or passing grade:

```bash
python main.py --input input/grades --masterlist input/masterlist/masterlist.csv --output output/passed_midterm_report.xlsx --passing-grade 75
```

## 4. How passing is computed

The tool detects columns by Row 1 headers using flexible aliases.

Required processable columns:

- `StudentName`
- `MidtermExam`
- `MidtermGrade`

`StudentNumber` is also detected when present. If it is missing or blank, passed rows are still included. The tool tries to fill the missing number from `input/masterlist/masterlist.csv` by matching `StudentName` to masterlist `Name`.

Name matching is normalized exact matching:

- Case-insensitive.
- Ignores punctuation and extra spaces.
- Does not use fuzzy matching.

A student is included in the `PassedStudents` sheet when:

```text
MidtermGrade >= passing grade
```

By default, the passing grade is `75`.

## 5. What the Issues sheet means

The `Issues` sheet records rows or files that need attention, including:

- Workbooks that could not be opened.
- Sheets missing required columns.
- Files with no processable sheet.
- Blank or non-numeric `MidtermGrade` values.
- Missing `StudentNumber` columns.
- Missing or invalid `masterlist.csv`.
- Missing input files or input folder.

The output workbook contains:

- `PassedStudents`: all passing students and their midterm grades.
- `Issues`: rows and files that could not be processed cleanly.
