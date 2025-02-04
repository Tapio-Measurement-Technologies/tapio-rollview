import gettext
import os
from utils import preferences
import settings

def set_translation(lang):
    locale_dir = settings.LOCALE_FILES_PATH
    lang_translation = gettext.translation('messages', localedir=locale_dir, languages=[lang], fallback=True)
    lang_translation.install()
    return lang_translation.gettext  # Return gettext function

# Global _() function
_ = set_translation(preferences.locale or settings.LOCALE_DEFAULT)