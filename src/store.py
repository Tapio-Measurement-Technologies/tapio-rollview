import settings
from models.Profile import RollDirectory
from typing import List
from PySide6.QtCore import Qt
import os

try:
    from version import __version__
    app_version = __version__
except ImportError:
    app_version = "(development version)"

log_manager = None
connections = []
profiles = []
selected_profile = None
selected_directory = None
root_directory = settings.ROOT_DIRECTORY

# Current sort criteria
current_sort_column = 3 # Default to date modified
current_sort_order = Qt.SortOrder.DescendingOrder

# Used in statistics analysis
# TODO: Refactor this to be used also elsewhere (e.g. atm hidden state is duplicated)
roll_directories: List[RollDirectory] = []

def get_profile_by_filename(filename):
    for profile in profiles:
        if profile.path == filename or profile.name == filename:
            return profile
    return None

def sort_profiles(column_index=None, sort_order=None):
    """
    Sort the profiles list in place by the specified column and order.
    If no arguments provided, uses the current sort criteria from state.

    Args:
        column_index: One of 0 (name), 1 (size), 3 (date_modified), 4 (profile_length), 5 (show_hide)
        sort_order: Qt.SortOrder.AscendingOrder or Qt.SortOrder.DescendingOrder
    """
    global profiles, current_sort_column, current_sort_order

    # Update state if new criteria provided
    if column_index is not None:
        current_sort_column = column_index
    if sort_order is not None:
        current_sort_order = sort_order

    # Use current state for sorting
    reverse = (current_sort_order == Qt.SortOrder.DescendingOrder)

    # Define sort key functions for each column
    sort_keys = {
        0: lambda p: os.path.basename(p.path).lower(),
        1: lambda p: p.file_size,
        3: lambda p: p.date_modified,
        4: lambda p: p.profile_length,
        5: lambda p: p.hidden,
    }

    # Get the appropriate sort key function
    key_func = sort_keys.get(current_sort_column)

    if key_func:
        profiles.sort(key=key_func, reverse=reverse)
    else:
        print(f"Warning: Unknown sort column '{current_sort_column}', profiles not sorted")
