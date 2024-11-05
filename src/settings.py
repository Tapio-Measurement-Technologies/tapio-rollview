from utils.plot_limits import constant, rel_max, rel_min, rel_mean
import numpy as np
import logging

DEFAULT_ROLL_DIRECTORY = '.tapiorqp'

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

SERIAL_SCAN_INTERVAL = 1000
SERIAL_PORT_TIMEOUT = 0.2


SAMPLE_INTERVAL = 1000  # Samples per meter in raw data

FILTER_NUMTAPS = 50

# Define the band pass filter, units are in cycles per meter
BAND_PASS_LOW = 0
BAND_PASS_HIGH = 30

ALERT_LIMITS_DEFAULT = [
    {
        "name": "mean_g",
        "label": "Mean",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "stdev_g",
        "label": "Stdev",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "cv_pct",
        "label": "CV",
        "units": "%",
        "min": None,
        "max": None
    },
    {
        "name": "min_g",
        "label": "Min",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "max_g",
        "label": "Max",
        "units": "g",
        "min": None,
        "max": None
    },
    {
        "name": "pp_g",
        "label": "P-p",
        "units": "g",
        "min": None,
        "max": None
    }
]

PROFILE_STATISTICS = [{
    "name": "Mean",
    "unit": "g",
    "func": np.mean,
    "limits": [None, 10]
}, {
    "name": "Standard deviation",
    "unit": "g",
    "func": np.std,
    "limits": None
}, {
    "name": "CV",
    "unit": "%",
    "func": lambda f: (np.mean(f) / np.std(f)),
    "limits": [0, 10]
}, {
    "name": "Min",
    "unit": "g",
    "func": np.min,
    "limits": None
}, {
    "name": "Max",
    "unit": "g",
    "func": np.max,
    "limits": None
}, {
    "name": "P-P",
    "unit": "g",
    "func": lambda f: np.max - np.min,
    "limits": None
}]


SHOW_SPECTRUM = False
NPERSEG = 3000
NOVERLAP = 0.75
SPECTRUM_LOWER_LIMIT = 0
SPECTRUM_UPPER_LIMIT = 60
SPECTRUM_WAVELENGTH_TICKS = True

CONTINUOUS_MODE = False
UNIT = "BC Hardness [g]"

# Configure logging
logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    level=logging.ERROR)

try:
    from local_settings import *
except:
    print("No local settings")
