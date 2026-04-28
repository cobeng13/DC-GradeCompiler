import argparse
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List


TOOL_ROOT = Path(__file__).resolve().parent


@dataclass
class ResetPlan:
    remove_files: List[Path] = field(default_factory=list)
    remove_dirs: List[Path] = field(default_factory=list)
    ensure_dirs: List[Path] = field(default_factory=list)
    ensure_files: List[Path] = field(default_factory=list)

    def all_removals(self) -> Iterable[Path]:
        yield from self.remove_files
        yield from self.remove_dirs


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _assert_safe_target(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root or not _is_within(resolved_path, resolved_root):
        raise ValueError(f"Refusing to remove unsafe path: {path}")


def build_reset_plan(base_dir: Path = TOOL_ROOT, include_inputs: bool = False) -> ResetPlan:
    base_dir = base_dir.resolve()
    plan = ResetPlan()

    data_dir = base_dir / "data"
    output_dir = base_dir / "output"
    test_tmp_dir = base_dir / ".test_tmp"

    db_path = data_dir / "grade_compiler.sqlite3"
    if db_path.exists():
        plan.remove_files.append(db_path)

    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                plan.remove_dirs.append(child)
            else:
                plan.remove_files.append(child)

    if test_tmp_dir.exists():
        plan.remove_dirs.append(test_tmp_dir)

    for pycache_dir in base_dir.rglob("__pycache__"):
        plan.remove_dirs.append(pycache_dir)

    for pyc_file in base_dir.rglob("*.pyc"):
        plan.remove_files.append(pyc_file)

    if include_inputs:
        for input_subdir in [base_dir / "input" / "grades", base_dir / "input" / "masterlist"]:
            if not input_subdir.exists():
                continue
            for child in input_subdir.iterdir():
                if child.name == ".gitkeep":
                    continue
                if child.is_dir():
                    plan.remove_dirs.append(child)
                else:
                    plan.remove_files.append(child)

    plan.ensure_dirs.extend([data_dir, output_dir])
    plan.ensure_files.append(output_dir / ".gitkeep")
    return plan


def apply_reset_plan(plan: ResetPlan, base_dir: Path = TOOL_ROOT, dry_run: bool = False) -> None:
    base_dir = base_dir.resolve()

    for path in plan.remove_files:
        _assert_safe_target(path, base_dir)
        if dry_run:
            continue
        if path.exists():
            path.unlink()

    for path in sorted(plan.remove_dirs, key=lambda item: len(item.parts), reverse=True):
        _assert_safe_target(path, base_dir)
        if dry_run:
            continue
        if path.exists():
            shutil.rmtree(path)

    if dry_run:
        return

    for path in plan.ensure_dirs:
        if not _is_within(path, base_dir):
            raise ValueError(f"Refusing to create unsafe directory: {path}")
        path.mkdir(parents=True, exist_ok=True)

    for path in plan.ensure_files:
        if not _is_within(path, base_dir):
            raise ValueError(f"Refusing to create unsafe file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)


def print_plan(plan: ResetPlan, dry_run: bool) -> None:
    action = "Would remove" if dry_run else "Will remove"
    removals = list(plan.all_removals())
    if removals:
        print(f"{action}:")
        for path in removals:
            print(f"  {path}")
    else:
        print("No generated files need removal.")

    if dry_run:
        return

    print("Will ensure:")
    for path in plan.ensure_dirs:
        print(f"  {path}")
    for path in plan.ensure_files:
        print(f"  {path}")


def confirm_or_exit(include_inputs: bool) -> None:
    prompt = "Reset generated test state"
    if include_inputs:
        prompt += " and delete local input files"
    prompt += "? Type YES to continue: "

    if input(prompt).strip() != "YES":
        raise SystemExit("Reset cancelled.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset generated DB, report, cache, and test scratch state."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting anything.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts.",
    )
    parser.add_argument(
        "--include-inputs",
        action="store_true",
        help="Also delete local files under input/grades and input/masterlist.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.include_inputs and not args.yes and not args.dry_run:
        print("This will delete local grading inputs and masterlist files.")

    plan = build_reset_plan(TOOL_ROOT, include_inputs=args.include_inputs)
    print_plan(plan, dry_run=args.dry_run)

    if args.dry_run:
        return

    if not args.yes:
        confirm_or_exit(args.include_inputs)

    apply_reset_plan(plan, TOOL_ROOT)
    print("Test state reset complete.")


if __name__ == "__main__":
    main()
