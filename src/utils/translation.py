import gettext
from utils import po_compile
from utils import preferences
import settings

# The .mo catalogs are generated from translations/*.po and untracked; a
# checkout compiles them here so a fresh clone or a pulled .po change is
# translated without a separate build step.
po_compile.ensure_compiled()


def set_translation(lang):
    locale_dir = settings.LOCALE_FILES_PATH
    lang_translation = gettext.translation('messages', localedir=locale_dir, languages=[lang], fallback=True)
    lang_translation.install()
    return lang_translation.gettext  # Return gettext function

# Global _() function
_ = set_translation(preferences.locale or settings.LOCALE_DEFAULT)
