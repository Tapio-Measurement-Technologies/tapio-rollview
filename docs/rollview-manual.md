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

## Directory Selection
- RollView will display all roll data in the currently selected working directory.
- By default, RollView uses the folder `.tapiorqp` under the user's home directory as the working directory.
- The working directory can be changed in the user interface with the **Change directory** button.
- The default working directory can be changed by providing the software with custom settings.

## Synchronization
- On sync, the contents of the device SD card are synchronized to the computer using the ZMODEM protocol over serial connection.

## Statistics
The displayed statistics are based on the mean profile (calculated as the mean of multiple measured profiles in the same folder).

Available statistics are:
- **Mean [g]:** Mean hardness of the mean hardness profile.
- **Stdev [g]:** Standard deviation of the mean hardness profile.
- **CV [%]:** Coefficient of variation, standard deviation normalized by the mean.
- **Min [g]:** Smallest hardness value of the mean hardness profile.
- **Max [g]:** Largest hardness value of the mean hardness profile.
- **P-p [g]:** Peak-to-peak, the difference between the largest and smallest hardness values in the mean profile.


## Settings System
The settings system in Tapio RollView allows users to customize the software's behavior by overriding default settings.

- **Default settings**: The software comes with a set of default settings suitable for most use cases. [View the file containing a list of default settings](https://github.com/Tapio-Measurement-Technologies/tapio-rollview/blob/main/src/settings.py)
- **Custom settings**: Users can create a custom settings file, such as `local_settings.py`, to override these defaults. This custom file should follow the same syntax as the default settings file `settings.py`. When launching the software, the custom settings file can be provided as a parameter, allowing the software to use these custom configurations instead of the defaults.
- **Retaining defaults**: Any settings not specified in the custom file will automatically retain their default values. This means users only need to specify the settings they wish to change in the custom settings file.
- **Shortcut to Windows executable**: It's common to create a shortcut that automatically launches the software with the custom settings file included as a parameter. This streamlines the process of using custom configurations.

## Postprocessor System
The postprocessor system in Tapio RollView can be used to automate tasks that need to be performed after data synchronization.

- **Default postprocessors**: The software includes three default postprocessors: Export to Excel file, Export to JSON file, and Export plot image. These postprocessors automatically create corresponding export files in the roll folder where the original data was read from.
- **Activation**: Postprocessors can be activated from the Postprocessors menu. Once activated, they run automatically after synchronizing new files from an RQP Live.
- **Manual re-run**: Users can manually trigger a re-run of activated postprocessors for all previous measurements (all roll folders in the current working directory) from the Postprocessors menu by selecting **Run postprocessors**. By default, this manual re-run is limited to files no older than 10 days, but this limit can be changed by modifying the setting `POSTPROCESSORS_RECENT_CUTOFF_TIME_DAYS`.
- **Custom postprocessors**: Users can create additional postprocessors to perform custom tasks, such as automatically exporting data to mill systems. These custom postprocessors must follow the same syntax as the default ones. Custom postprocessors can be placed in a folder named `postprocessors` in the default working directory `~/.tapiorqp/` (this default working directory can be changed in settings).
- **Loading custom postprocessors**: On software launch, the software scans the `postprocessors` folder in the default working directory and loads any additional postprocessors found there. These custom postprocessors will appear with the default ones in the Postprocessors menu, from where they can be activated and deactivated.
