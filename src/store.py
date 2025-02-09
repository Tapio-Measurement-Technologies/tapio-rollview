import settings

connections = []
profiles = []
selected_profile = None
selected_directory = None
root_directory = settings.ROOT_DIRECTORY

def get_profile_by_filename(filename):
    for profile in profiles:
        if profile.path == filename or profile.name == filename:
            return profile
    return None
