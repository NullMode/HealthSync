# HealthSync

This is heavily inspired by the work in https://github.com/blueostrich18/health thank you for laying the groundwork!

This script is designed to pull data from various sources and populate a Google Sheet with the data.

# Requirements

- Python 3.11
- Virtualenv

## Installation

```bash
git clone https://github.com/NullMode/HealthSync
cd HealthSync 
# You may need to specify python3.11 if you have multiple versions of python installed
python -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

You may get some errors here that indicate you need to install some system packages.

## Setup and Config

### Spreadsheet Map Template

Running the script for the first time will generate a `spreadsheet_map.json` file for your review. This file is used to map the data from the various sources to the columns in the spreadsheet.

The currently supported sources are:

- Whoop
- MyFitnessPal

Inspecting the generated file will show you what information is being pulled from each source and where it is being placed in the spreadsheet.

Currently, all data points from the services are in the map.

### Credential File

Running the script for the first time will generate a `health.ini` file for your review. This file is used to store the credentials for the various services, as well as other general information.

More details below.

Information on the values needed can also be found in the `health.ini` file, or the `health.ini.template` file.

#### Whoop

This uses an old library for interaction with whoop using your username and password. If you don't supply them in the `health.ini` file you will be prompted for them if it is enabled.

#### MyFitnessPal

You must be logged into MyFitnessPal in your browser and then run the script. The script will then use the cookies from your browser to authenticate. The browser used will be what is set in the config. 

There is support for:

- chrome
- firefox
- edge
- opera
- safari
- chromium

Note: extensive testing has only been performed with Chrome.

#### Google

The script uses the Google Sheets API to interact with the spreadsheet. You will need to create a project in the Google Developer Console and enable the Google Sheets API. You will also need to create a service account and download the JSON key file.

Instructions how to do this can be found here - https://support.google.com/a/answer/7378726

You will need to share the spreadsheet with the email address of the service account (found in the JSON key file).

## Running

To run the script simply run the following command whilst in the virtual environment.

```bash
python main.py
```

You may be prompted to provide credentials if you didn't provide them in the INI file.

You may also be prompted for credentials to access the cookie store on your machine.

On Windows you may need to close the browser which is authenticated with MyFitnessPal before running the script.

## Other Notes

There is a `day_calc.py` script that can be used to calculate what your initial start day was (say you want to start using this script but you're already on Week 55).

Simply take note of the date of the last day of the current week you are tracking along with the week number to give you your starting date - this can then be used in the config file.

```sh
$ python script.py --date 2025-01- --week 2
python day_calc.py --date "2025-01-26" --week 2
Week 2 - Day 7: Sunday - 2025-01-26
Week 2 - Day 6: Saturday - 2025-01-25
Week 2 - Day 5: Friday - 2025-01-24
Week 2 - Day 4: Thursday - 2025-01-23
Week 2 - Day 3: Wednesday - 2025-01-22
Week 2 - Day 2: Tuesday - 2025-01-21
Week 2 - Day 1: Monday - 2025-01-20

Week 1 - Day 7: Sunday - 2025-01-19
Week 1 - Day 6: Saturday - 2025-01-18
Week 1 - Day 5: Friday - 2025-01-17
Week 1 - Day 4: Thursday - 2025-01-16
Week 1 - Day 3: Wednesday - 2025-01-15
Week 1 - Day 2: Tuesday - 2025-01-14
Week 1 - Day 1: Monday - 2025-01-13
```