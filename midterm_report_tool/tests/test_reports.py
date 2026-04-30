import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reports import (
    build_matrix_students,
    names_are_ordered_merge_match,
    ordered_character_match_count,
)


class ReportMatrixMergeTests(unittest.TestCase):
    def test_ordered_character_match_counts_subsequence_overlap(self):
        self.assertEqual(
            ordered_character_match_count(
                "andayaisiahximuelcarandang", "andayaisiahximuel"
            ),
            len("andayaisiahximuel"),
        )

    def test_ordered_name_merge_matches_close_typo_variants(self):
        self.assertTrue(
            names_are_ordered_merge_match(
                "Culis, Mizzy Marimontt Bejasa", "Culis, Mizzy Mariomntt Bejasa"
            )
        )

    def test_ordered_name_merge_rejects_shortened_or_different_students(self):
        self.assertFalse(
            names_are_ordered_merge_match(
                "Andaya, Isiah Ximuel Carandang", "Andaya, Isiah Ximuel"
            )
        )
        self.assertFalse(
            names_are_ordered_merge_match("Anog, Alyssa Naga?o", "Anog, Alyssa")
        )
        self.assertFalse(
            names_are_ordered_merge_match(
                "Concepcion, Angel Tom Rasay", "Concepcion, Tom"
            )
        )
        self.assertFalse(
            names_are_ordered_merge_match("Mau, Bronny Junior", "Mau, Bronny")
        )
        self.assertFalse(
            names_are_ordered_merge_match(
                "Catibog, Danielle Ysabel Lanip", "Catibog, Denise Alexa Lanip"
            )
        )
        self.assertFalse(
            names_are_ordered_merge_match(
                "Bautista, Elaiza Kathrina Calayan",
                "Bautista, Eloiza Katherine Calayan",
            )
        )

    def test_matrix_students_merge_compatible_name_variants(self):
        students = build_matrix_students(
            [
                {
                    "StudentName": "Culis, Mizzy Marimontt Bejasa",
                    "Section": "1A",
                    "NormalizedName": "culis mizzy marimontt bejasa",
                }
            ],
            [
                {
                    "StudentName": "Culis, Mizzy Mariomntt Bejasa",
                    "Section": "1A",
                    "Course": "CourseA",
                    "MidtermGrade": 90,
                },
                {
                    "StudentName": "Culis, Mizzy Marimontt Bejasa",
                    "Section": "2A",
                    "Course": "CourseB",
                    "MidtermGrade": 91,
                },
            ],
        )

        self.assertEqual(len(students), 2)
        merged_student = students[0]
        self.assertEqual(
            set(merged_student["NormalizedAliases"]),
            {"culis mizzy marimontt bejasa", "culis mizzy mariomntt bejasa"},
        )


if __name__ == "__main__":
    unittest.main()
