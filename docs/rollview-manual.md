# Tapio RollView Manual

## Installation

### Standard installation (standard postprocessors and settings)
- RollView is released as a Windows executable which does not require separate installation.
- Download the latest release as a Windows executable from the [Releases page](https://github.com/Tapio-Measurement-Technologies/tapio-rollview/releases)
- The .exe can be run directly without installation
 
### Custom installation (with source code for configuring custom features)
To install Tapio RollView with source code for configuring custom features, follow the steps below:

- [Install Python 3.12.1](https://www.python.org/downloads/release/python-3121/)
- [Install Git](https://git-scm.com/)

Run the following in a command prompt:
```bash
# First navigate to the preferred installation folder
# Clone the repository
git clone https://github.com/Tapio-Measurement-Technologies/tapio-rollview
# Navigate to the project directory
cd tapio-rollview
# Run the installation script (installs python dependencies in a virtualenv, creates local settings, launch script and shortcut)
./install.bat
```


## Directory selection
- By default, RollView uses the folder .tapiorqp under the user's home directory.

## Synchronization
- On sync, the contents of the device SD card are synchronized to the computer using the ZMODEM protocol.

## Statistics
The displayed statistics are based on the mean profile (which is calculated as the mean of multiple measured profiles in the same folder).

Available statistics are:
- Mean [g]: Mean hardness of the mean hardness profile
- Stdev [g]: Standard deviation of the mean hardness profile
- CV [%]: Standard deviation normalized by the mean
- Min [g]: Smallest hardness value of the mean hardness profile
- Max [g]: Largest hardness value of the mean hardness profile
- P-p [g]: Peak-to-peak, difference between largest and smallest hardness values in the mean proile

## Postprocessor system
- Postprocessors are run after synchronizing new files from an RQP Live
- Postprocessors can be activated from the menu
- A re-run of activated postprocessors for all files can be triggered from the menu



