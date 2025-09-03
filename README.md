# HealthSync

This is heavily inspired by the work in https://github.com/blueostrich18/health thank you for laying the groundwork!

This script is designed to pull data from various sources and populate a Google Sheet with the data.

The script works by going through sheets labelled "Week X" where X is the week number. The script will then go through each day of the week and pull data from the various sources and populate the sheet with the data.

The sheet checks a cell to see if it is populated with "Y" indicating that it has been completed. If it is not populated with "Y" then the script will pull the data from the various sources and populate the sheet with the data.

The script will then check the next week and repeat the process until it reaches today's date or until it runs out of sheets to process.

There is a mapping file that is used to map the data from the various sources to the columns in the spreadsheet. The mapping file is a JSON file that contains the mapping for each source.

See below for more details on how to set up the script and the mapping file.

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

When running the script for the first time three files will be generated in the root of the project:

- `health.ini`
- `spreadsheet_map.json`
- `config.json`

You will be required to make changes to both of these files - more information on this below.

### General

Within `health.ini` you will need to provide the following information:

- `start_date` - Example: `2025-01-13`
- `start_week` - Example: `1`
- `timezone` - Example: `Europe/London`

The `start_date` is the date of the first day of the first week you want to track. Use the `day_calc.py` script to help you calculate this if you are starting from a week that is not 1 (see below).

The `start_week` is the week number of the first week you want to track. Since the script always starts at 1, you may want to change this to a higher number eventually to speed up the scripts execution.

The `timezone` is the timezone you are in, this is used to help covert dates from Whoop to the correct timezone.

### Spreadsheet Map Template (spreadsheet_map.json)

Running the script for the first time will generate a `spreadsheet_map.json` file for your review. This file is used to map the data from the various sources to the columns in the spreadsheet.

The currently supported sources are:

- Whoop
- MyFitnessPal

Inspecting the generated file will show you what information is being pulled from each source and where it is being placed in the spreadsheet.

Currently, all data points from the services are in the map.

### Credential File (health.ini)

Running the script for the first time will generate a `health.ini` file for your review. This file is used to store the credentials for various services, as well as other general information.

More details below.

Information on the values needed can also be found in the `health.ini` file, or the `health.ini.template` file.


#### MyFitnessPal

You must be logged into MyFitnessPal in your browser and then run the script. The script will then use the cookies from your browser to authenticate. The browser used will be what is set in the config. 

There is support for:

- chrome
- firefox
- edge
- opera
- safari
- chromium

Note: extensive testing has only been performed with Chrome & Firefox.

#### Google

The script uses the Google Sheets API to interact with the spreadsheet. You will need to create a project in the Google Developer Console and enable the Google Sheets API. You will also need to create a service account and download the JSON key file.

Instructions how to do this can be found here - https://support.google.com/a/answer/7378726

You will need to share the spreadsheet with the email address of the service account (found in the JSON key file).

### Whoop Creds (config.json)

In order to connect to Whoop you will need to login to the developer portal and create an application.

Create a new app here - https://developer-dashboard.whoop.com/

- Fill out the various fields for a call back URL something liek http://localhost:1234 is fine. 
- Select all scopes.
- No web hooks are required

You will then need to use the `client id`, `client secret` and the `redirect url` in the `config.json` file.

On first one you will need to authenticate to whoop and it will redirect to the localhost provided above (if used). You will need to copy and paste this url into the tool when requested. Another file called `whoop_credentials.json` will be created which will store your current access token and refresh token among other things.

The underlying library used here is called Whoopy using my fork with some updates to the recovery endpoint (https://github.com/NullMode/whoopy)

## Running

To run the script simply run the following command whilst in the virtual environment.

```bash
python main.py
```

You may be prompted to provide credentials if you didn't provide them in the INI file.

You may also be prompted for credentials to access the cookie store on your machine.

You will be prompted to authenticate to whoop if enabled.

On Windows you may need to close the browser which is authenticated with MyFitnessPal before running the script.

## Other Notes

There is a `day_calc.py` script that can be used to calculate what your initial start day was (say you want to start using this script but you're already on Week 55).

Simply take note of the date of the last day of the current week you are tracking along with the week number to give you your starting date - this can then be used in the config file.

```sh
$ python day_calc.py --date "2025-01-26" --week 2
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