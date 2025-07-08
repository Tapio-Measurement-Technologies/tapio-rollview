import settings
from models.Profile import RollDirectory
from typing import List

log_manager = None
connections = []
profiles = []
selected_profile = None
selected_directory = None
root_directory = settings.ROOT_DIRECTORY

# Used in statistics analysis
# TODO: Refactor this to be used also elsewhere (e.g. atm hidden state is duplicated)
roll_directories: List[RollDirectory] = []

def get_profile_by_filename(filename):
    for profile in profiles:
        if profile.path == filename or profile.name == filename:
            return profile
    return None
