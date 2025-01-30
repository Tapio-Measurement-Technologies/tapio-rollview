import logging
import os

DEFAULT_ROLL_DIRECTORY = '.tapiorqp'
PREFERENCES_FILENAME = 'preferences.json'
PREFERENCES_FILE_PATH = os.path.join(DEFAULT_ROLL_DIRECTORY, PREFERENCES_FILENAME)

# limits can be:
# - constant(value) : constant limit
# - rel_min(factor) : limit relative to mean profile min
# - rel_max(factor) : limit relative to mean profile max
# - rel_mean(factor) : limit relative to mean profile mean
# - None : automatic scaling
Y_LIM_LOW = None
Y_LIM_HIGH = None
GRID = True

MEAN_PROFILE_LINE_WIDTH = 2.8
MEAN_PROFILE_LINE_COLOR = "tab:purple"
SELECTED_PROFILE_LINE_WIDTH = 2

# See python strftime
# https://docs.python.org/3/library/datetime.html
CUSTOM_DATE_FORMAT = None

SAMPLE_INTERVAL = 1000  # Samples per meter in raw data

FILTER_NUMTAPS = 50

# Define the band pass filter, units are in cycles per meter
BAND_PASS_LOW = 0
BAND_PASS_HIGH = 30

DEFAULT_ENABLED_POSTPROCESSORS = [
    'excel_export',
    'plot_export'
]

SHOW_ALL_COM_PORTS_DEFAULT = False
RECALCULATE_MEAN_DEFAULT = True
LOCALE_DEFAULT = "en"

ALERT_LIMITS_DEFAULT = [
    {
        "name": "mean_g",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "stdev_g",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "cv_pct",
        "units": "%",
        "min": None,
        "max": None
    },
    {
        "name": "min_g",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "max_g",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "pp_g",
        "units": "g",
        "min": None,
        "max": None
    }
]

SHOW_SPECTRUM = False
NPERSEG = 3000
NOVERLAP = 0.75
SPECTRUM_LOWER_LIMIT = 0
SPECTRUM_UPPER_LIMIT = 60
SPECTRUM_WAVELENGTH_TICKS = True

CONTINUOUS_MODE = False

POSTPROCESSORS_RECENT_CUTOFF_TIME_DAYS = None

# Configure logging
logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    level=logging.ERROR)


try:
    from local_settings import *
except:
    print("No local settings")
