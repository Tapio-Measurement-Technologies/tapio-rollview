from utils.profile_stats import STAT_SPECS, Stats, calc_mean_profile
from utils.translation import _
from models.Profile import Profile
import pandas as pd
import numpy as np
import os


EXPORT_FLOAT_NUM_DECIMAL_PLACES = 3
STATISTICS_SHEET_NAME = "Statistics"
MEAN_PROFILE_SHEET_NAME = "Mean profile"

# Unit used for profile lengths in the Statistics sheet.
# Supported values: "m", "cm", "mm", and "in".
PROFILE_LENGTH_UNIT = "m"
PROFILE_LENGTH_UNIT_CONVERSION_FACTORS = {
    "m": 1.0,
    "cm": 100.0,
    "mm": 1000.0,
    "in": 39.3701,
}

description = _("POSTPROCESSOR_NAME_EXCEL_EXPORT")


def _statistic_headers():
    """Return statistic headers in the same order as the RollView UI."""
    return [
        f"{spec['label']} [{spec['unit']}]"
        for spec in STAT_SPECS
    ]


def _calculate_statistics(profile_data, stats=None):
    """Calculate the UI statistics and convert non-finite values to blanks."""
    stats = stats or Stats()
    values = []

    for spec in STAT_SPECS:
        stat_function = getattr(stats, spec["analysis_key"])
        with np.errstate(divide="ignore", invalid="ignore"):
            value = float(stat_function(profile_data))
        values.append(
            round(value, EXPORT_FLOAT_NUM_DECIMAL_PLACES)
            if np.isfinite(value)
            else None
        )

    return values


def _profile_length_conversion_factor():
    """Return the configured conversion factor or fail with a clear message."""
    if PROFILE_LENGTH_UNIT not in PROFILE_LENGTH_UNIT_CONVERSION_FACTORS:
        supported_units = ", ".join(PROFILE_LENGTH_UNIT_CONVERSION_FACTORS)
        raise ValueError(
            f"Unsupported PROFILE_LENGTH_UNIT '{PROFILE_LENGTH_UNIT}'. "
            f"Supported values: {supported_units}."
        )
    return PROFILE_LENGTH_UNIT_CONVERSION_FACTORS[PROFILE_LENGTH_UNIT]


def _calculate_profile_length(distances):
    """Calculate the measured distance span in the configured export unit."""
    conversion_factor = _profile_length_conversion_factor()

    distances = np.asarray(distances, dtype=float)
    if len(distances) == 0:
        return None

    length_metres = float(np.max(distances) - np.min(distances))
    length = length_metres * conversion_factor
    return round(length, EXPORT_FLOAT_NUM_DECIMAL_PLACES)


def _write_statistics_sheet(writer, folder_name, profile_records, mean_profile):
    """Create a compact statistical summary as the workbook's first sheet."""
    workbook = writer.book
    worksheet = workbook.add_worksheet(STATISTICS_SHEET_NAME)
    writer.sheets[STATISTICS_SHEET_NAME] = worksheet

    statistic_headers = _statistic_headers()
    table_headers = [
        "Profile",
        f"Profile length [{PROFILE_LENGTH_UNIT}]",
        *statistic_headers,
    ]
    last_column = len(table_headers) - 1

    title_format = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "font_size": 16,
        "bg_color": "#1F4E78",
        "align": "left",
        "valign": "vcenter",
    })
    section_format = workbook.add_format({
        "bold": True,
        "font_color": "#1F4E78",
        "bg_color": "#D9EAF7",
        "bottom": 1,
        "bottom_color": "#9EADBA",
        "align": "left",
        "valign": "vcenter",
    })
    metadata_label_format = workbook.add_format({
        "bold": True,
        "font_color": "#404040",
    })
    metadata_value_format = workbook.add_format({
        "font_color": "#202020",
    })
    integer_format = workbook.add_format({
        "font_color": "#202020",
        "num_format": "0",
    })
    header_format = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#4472C4",
        "border": 1,
        "border_color": "#D9E2F3",
        "align": "center",
        "valign": "vcenter",
        "text_wrap": True,
    })
    profile_name_format = workbook.add_format({
        "font_color": "#202020",
        "border": 1,
        "border_color": "#D9E2F3",
    })
    number_format = workbook.add_format({
        "font_color": "#202020",
        "border": 1,
        "border_color": "#D9E2F3",
        "num_format": f"0.{'0' * EXPORT_FLOAT_NUM_DECIMAL_PLACES}",
    })
    mean_profile_name_format = workbook.add_format({
        "bold": True,
        "font_color": "#1F4E78",
        "bg_color": "#EAF2F8",
        "border": 1,
        "border_color": "#B4C6E7",
    })
    mean_number_format = workbook.add_format({
        "bold": True,
        "font_color": "#1F4E78",
        "bg_color": "#EAF2F8",
        "border": 1,
        "border_color": "#B4C6E7",
        "num_format": f"0.{'0' * EXPORT_FLOAT_NUM_DECIMAL_PLACES}",
    })

    worksheet.hide_gridlines(2)
    worksheet.set_tab_color("#1F4E78")
    worksheet.set_row(0, 25)
    worksheet.set_row(5, 22)
    worksheet.set_row(9, 22)
    worksheet.set_column(0, 0, 24)
    worksheet.set_column(1, 1, 19)
    worksheet.set_column(2, last_column, 15)
    worksheet.set_landscape()
    worksheet.fit_to_pages(1, 0)
    worksheet.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)

    worksheet.merge_range(
        0, 0, 0, last_column, "Folder statistics", title_format)
    worksheet.write(2, 0, "Folder", metadata_label_format)
    worksheet.write(2, 1, folder_name, metadata_value_format)
    worksheet.write(3, 0, "Total profiles", metadata_label_format)
    worksheet.write_number(3, 1, len(profile_records), integer_format)

    worksheet.merge_range(
        5, 0, 5, last_column, "Mean profile statistics", section_format)
    worksheet.write_row(6, 0, table_headers, header_format)

    mean_profile_data = (mean_profile[0], mean_profile[1])
    mean_statistics = _calculate_statistics(mean_profile_data)
    worksheet.write(7, 0, MEAN_PROFILE_SHEET_NAME, mean_profile_name_format)
    mean_profile_length = _calculate_profile_length(mean_profile[0])
    worksheet.write_number(
        7, 1, mean_profile_length, mean_number_format)
    for column, value in enumerate(mean_statistics, start=2):
        if value is None:
            worksheet.write_blank(7, column, None, mean_number_format)
        else:
            worksheet.write_number(7, column, value, mean_number_format)

    worksheet.merge_range(
        9, 0, 9, last_column, "Profile statistics", section_format)
    worksheet.write_row(10, 0, table_headers, header_format)

    stats = Stats()
    first_profile_row = 11
    for row_offset, (file_name, profile) in enumerate(profile_records):
        row = first_profile_row + row_offset
        distances, values = calc_mean_profile([profile])
        profile_statistics = _calculate_statistics((distances, values), stats)

        worksheet.write(row, 0, file_name, profile_name_format)
        profile_length = _calculate_profile_length(profile.data.distances)
        worksheet.write_number(row, 1, profile_length, number_format)
        for column, value in enumerate(profile_statistics, start=2):
            if value is None:
                worksheet.write_blank(row, column, None, number_format)
            else:
                worksheet.write_number(row, column, value, number_format)

    last_profile_row = first_profile_row + len(profile_records) - 1
    worksheet.autofilter(10, 0, last_profile_row, last_column)
    worksheet.freeze_panes(first_profile_row, 1)
    worksheet.print_area(0, 0, last_profile_row, last_column)


def _format_data_sheet(writer, sheet_name, dataframe):
    """Apply a small, consistent usability baseline to raw data sheets."""
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]
    header_format = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#4472C4",
        "border": 1,
        "border_color": "#D9E2F3",
    })

    worksheet.hide_gridlines(2)
    worksheet.freeze_panes(1, 0)
    worksheet.set_row(0, 22)
    worksheet.set_column(0, 1, 16)
    if len(dataframe.columns) > 2:
        worksheet.set_column(2, len(dataframe.columns) - 1, 18)
    worksheet.write_row(0, 0, dataframe.columns, header_format)
    worksheet.autofilter(0, 0, len(dataframe), len(dataframe.columns) - 1)
    worksheet.set_landscape()
    worksheet.fit_to_pages(1, 0)
    worksheet.repeat_rows(0)
    worksheet.print_area(0, 0, len(dataframe), len(dataframe.columns) - 1)
    worksheet.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)


def run(folder_path) -> bool:
    """Export a statistical summary, mean profile, and raw profiles to Excel."""
    _profile_length_conversion_factor()
    folder_name = os.path.basename(folder_path.rstrip('/\\'))
    excel_file_path = os.path.join(folder_path, f"{folder_name}.xlsx")

    profile_records = []
    data_sheets = []

    for file_name in sorted(os.listdir(folder_path)):
        if file_name.endswith('.prof') and file_name != 'mean.prof':
            file_path = os.path.join(folder_path, file_name)

            try:
                profile = Profile.fromfile(file_path)
                if profile is None or profile.data is None:
                    continue

                header = profile.header
                data = profile.data
                profile_records.append((file_name, profile))

                columns = {
                    'Distance': np.round(data.distances, EXPORT_FLOAT_NUM_DECIMAL_PLACES),
                    'Hardness value': np.round(data.hardnesses, EXPORT_FLOAT_NUM_DECIMAL_PLACES)
                }
                dataframe = pd.DataFrame(columns)
                dataframe.loc[0, 'Folder'] = folder_name
                dataframe.loc[0, 'Sample step'] = header.sample_step
                dataframe.loc[0, 'Serial number'] = header.serial_number
                dataframe.loc[0, '.prof file version'] = header.prof_version

                data_sheets.append((dataframe, file_name))
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue

    if not profile_records:
        print("No valid .prof files were found; no Excel file was created.")
        return False

    mean_profile = calc_mean_profile([profile for _, profile in profile_records])
    if len(mean_profile[1]) == 0:
        print("No valid profile samples were found; no Excel file was created.")
        return False

    mean_columns = {
        'Distance': np.round(mean_profile[0], EXPORT_FLOAT_NUM_DECIMAL_PLACES),
        'Hardness value': np.round(mean_profile[1], EXPORT_FLOAT_NUM_DECIMAL_PLACES)
    }
    mean_dataframe = pd.DataFrame(mean_columns)
    mean_dataframe.loc[0, 'Folder'] = folder_name
    data_sheets.insert(0, (mean_dataframe, MEAN_PROFILE_SHEET_NAME))

    with pd.ExcelWriter(excel_file_path, engine='xlsxwriter') as writer:
        _write_statistics_sheet(
            writer, folder_name, profile_records, mean_profile)

        for dataframe, sheet_name in data_sheets:
            dataframe.to_excel(writer, sheet_name=sheet_name, index=False)
            _format_data_sheet(writer, sheet_name, dataframe)

    print(f"Excel file '{excel_file_path}' has been created successfully.")
    return True
