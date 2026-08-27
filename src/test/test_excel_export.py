import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from xml.etree import ElementTree

import numpy as np

from models.Profile import Profile, ProfileData, ProfileHeader
from postprocessors import excel_export
from utils import preferences
import settings


SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _read_xlsx_sheet_names(workbook_path):
    with zipfile.ZipFile(workbook_path) as archive:
        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    return [
        sheet.attrib["name"]
        for sheet in root.findall(f".//{{{SPREADSHEET_NS}}}sheet")
    ]


def _read_sheet_cells(workbook_path, sheet_number=1):
    with zipfile.ZipFile(workbook_path) as archive:
        shared_strings_root = ElementTree.fromstring(
            archive.read("xl/sharedStrings.xml"))
        shared_strings = [
            "".join(node.text or "" for node in item.iter(f"{{{SPREADSHEET_NS}}}t"))
            for item in shared_strings_root.findall(f"{{{SPREADSHEET_NS}}}si")
        ]
        sheet_root = ElementTree.fromstring(
            archive.read(f"xl/worksheets/sheet{sheet_number}.xml"))

    cells = {}
    for cell in sheet_root.findall(f".//{{{SPREADSHEET_NS}}}c"):
        reference = cell.attrib["r"]
        value_node = cell.find(f"{{{SPREADSHEET_NS}}}v")
        if value_node is None:
            cells[reference] = None
        elif cell.attrib.get("t") == "s":
            cells[reference] = shared_strings[int(value_node.text)]
        else:
            cells[reference] = float(value_node.text)
    return cells


class TestExcelExport(unittest.TestCase):
    def setUp(self):
        self.original_excluded_regions_mode = preferences.excluded_regions_mode
        self.original_excluded_regions = preferences.excluded_regions
        preferences.excluded_regions_mode = settings.EXCLUDED_REGIONS_MODE_NONE
        preferences.excluded_regions = ""

    def tearDown(self):
        preferences.excluded_regions_mode = self.original_excluded_regions_mode
        preferences.excluded_regions = self.original_excluded_regions

    @staticmethod
    def _profile(path, values):
        values = np.asarray(values, dtype=float)
        return Profile(
            path=path,
            data=ProfileData(
                distances=np.arange(len(values), dtype=float),
                hardnesses=values,
            ),
            header=ProfileHeader(
                prof_version=1,
                serial_number="RQP-123",
                sample_step=1.0,
            ),
            file_size=128 + len(values) * 4,
            date_modified=0.0,
        )

    def test_statistics_follow_software_order(self):
        self.assertEqual(
            excel_export._statistic_headers(),
            [
                "Mean [g]",
                "Stdev [g]",
                "CV [%]",
                "Min [g]",
                "Max [g]",
                "P-p [g]",
                "Slope [g]",
            ],
        )

    def test_run_creates_statistics_as_first_sheet(self):
        with tempfile.TemporaryDirectory() as folder_path:
            folder_name = os.path.basename(folder_path)
            first_path = os.path.join(folder_path, "001.prof")
            second_path = os.path.join(folder_path, "002.prof")
            open(first_path, "wb").close()
            open(second_path, "wb").close()

            profiles = {
                first_path: self._profile(first_path, [1, 2, 3]),
                second_path: self._profile(second_path, [4, 6, 8]),
            }

            def fake_mean_profile(selected_profiles):
                if len(selected_profiles) == 2:
                    return np.array([0, 1, 2]), np.array([10, 20, 30])
                values = selected_profiles[0].data.hardnesses
                return np.arange(len(values), dtype=float), values

            with (
                patch.object(excel_export.Profile, "fromfile", side_effect=profiles.get),
                patch.object(excel_export, "calc_mean_profile", side_effect=fake_mean_profile),
                patch.object(excel_export, "PROFILE_LENGTH_UNIT", "cm"),
            ):
                self.assertTrue(excel_export.run(folder_path))

            workbook_path = os.path.join(folder_path, f"{folder_name}.xlsx")
            self.assertEqual(
                _read_xlsx_sheet_names(workbook_path),
                ["Statistics", "Mean profile", "001.prof", "002.prof"],
            )

            cells = _read_sheet_cells(workbook_path)
            self.assertEqual(cells["A1"], "Folder statistics")
            self.assertEqual(cells["A3"], "Folder")
            self.assertEqual(cells["B3"], folder_name)
            self.assertEqual(cells["A4"], "Total profiles")
            self.assertEqual(cells["B4"], 2)
            self.assertEqual(cells["A6"], "Mean profile statistics")
            self.assertEqual(
                [cells[f"{column}7"] for column in "ABCDEFGHI"],
                [
                    "Profile",
                    "Profile length [cm]",
                    "Mean [g]",
                    "Stdev [g]",
                    "CV [%]",
                    "Min [g]",
                    "Max [g]",
                    "P-p [g]",
                    "Slope [g]",
                ],
            )
            self.assertEqual(cells["A8"], "Mean profile")
            self.assertEqual(cells["B8"], 200)
            self.assertEqual(cells["C8"], 20)
            self.assertEqual(cells["F8"], 10)
            self.assertEqual(cells["G8"], 30)
            self.assertEqual(cells["H8"], 20)
            self.assertEqual(cells["A10"], "Profile statistics")
            self.assertEqual(cells["A12"], "001.prof")
            self.assertEqual(cells["A13"], "002.prof")
            self.assertEqual(cells["B12"], 200)
            self.assertEqual(cells["B13"], 200)
            self.assertEqual(cells["C12"], 2)
            self.assertEqual(cells["C13"], 6)

            mean_profile_cells = _read_sheet_cells(workbook_path, 2)
            self.assertEqual(mean_profile_cells["B1"], "Hardness value")
            self.assertEqual(mean_profile_cells["C1"], "Folder")

            profile_cells = _read_sheet_cells(workbook_path, 3)
            self.assertEqual(profile_cells["B1"], "Hardness value")
            self.assertEqual(profile_cells["C1"], "Folder")

    def test_profile_length_rejects_an_unsupported_unit(self):
        with patch.object(excel_export, "PROFILE_LENGTH_UNIT", "yards"):
            with self.assertRaisesRegex(ValueError, "Unsupported PROFILE_LENGTH_UNIT"):
                excel_export._calculate_profile_length([0, 1])


if __name__ == "__main__":
    unittest.main()
