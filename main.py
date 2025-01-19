from datetime import timedelta
from itertools import count
from whoop import WhoopClient
from gspread.cell import Cell
from gspread.utils import a1_to_rowcol

import getpass
import re
import browser_cookie3
import configparser
import datetime
import gspread
import json
import logging
import myfitnesspal
import os
import shutil
import sys
import time

logging.basicConfig(encoding='utf-8', level=logging.INFO)


INI = "health.ini"
TEMPLATE_INI = "health.ini.template"
SPREADSHEET_MAP = "spreadsheet_map.json"
SPREADSHEET_MAP_TEMPLATE = "spreadsheet_map.json.template"


def create_cell(coordinate, value):
    """
    Converts an A1-style coordinate and a value into a gspread Cell object.

    Args:
        coordinate (str): The A1-style cell coordinate (e.g., "C27").
        value (str): The value to set in the cell.

    Returns:
        Cell: A gspread Cell object with the specified coordinate and value.
    """
    row, col = a1_to_rowcol(coordinate)  # Convert A1 notation to row and column
    return Cell(row=row, col=col, value=value)


# temp method while waiting for mfp lib update
def get_measures(client, id, lower_date):
    data = {}
    stop = False
    for page_num in count(1, 1):
        url = f"https://www.myfitnesspal.com/measurements/edit?type={id}&page={page_num}"
        page = client._get_content_for_url(url)

        if res := re.search(r'\[\\"idm-user-with-consents\\"]"},{"state":{"data":{"items":(.*?)]', page):
            for item in json.loads(res[1] + ']'):
                if item['date'] < lower_date:
                    stop = True
                    break
                data[item['date']] = item['value']
        else:
            print('oops', len(page))
        if stop or re.search('"has_more":(.*?),', page)[1] == 'false':
            break

    return data


# temp method while waiting for mfp lib update
def latest_measures(client):
    url = "https://www.myfitnesspal.com/measurements/check-in"
    page = client._get_content_for_url(url)
    res = re.search(r'{"mutations":\[\],"queries":\[{"state":{"data":{"items":(.*?)]', page)
    data = {}
    for item in json.loads(res[1] + ']'):
        data[item['type']] = item['value']
    return data


def get_browser_cookies(browser, domain):
    if browser == "chrome":
        return browser_cookie3.chrome(domain_name=domain)
    elif browser == "firefox":
        return browser_cookie3.firefox(domain_name=domain)
    elif browser == "edge":
        return browser_cookie3.edge(domain_name=domain)
    elif browser == "opera":
        return browser_cookie3.opera(domain_name=domain)
    elif browser == "safari":
        return browser_cookie3.safari(domain_name=domain)
    elif browser == "chromium":
        return browser_cookie3.chromium(domain_name=domain)
    else:
        raise Exception("Invalid browser specified!")


def get_mfp_day_data(mfp_client, current_date):
    day_data = mfp_client.get_date(current_date.year, current_date.month, current_date.day)

    if not day_data.water:
        water = 0
    else:
        water = day_data.water

    logging.info(day_data)

    for item in ["calories", "carbohydrates", "fat", "protein", "fiber"]:
        if item not in day_data.totals:
            day_data.totals[item] = 0

    # Get weight
    current_date_str = current_date.strftime("%Y-%m-%d")
    try:
        weight = get_measures(mfp_client, "Weight", current_date_str)[current_date_str]
    except KeyError:
        weight = ""

    return {
        "water": water,
        "calories": day_data.totals["calories"],
        "carbs": day_data.totals["carbohydrates"],
        "fat": day_data.totals["fat"],
        "protein": day_data.totals["protein"],
        "fiber": day_data.totals["fiber"],
        "weight": weight,
    }


def get_whoop_day_data(whoop_client, date):
    cycle_date = date.strftime("%Y-%m-%d 12:00:00")

    # Sleep
    # Get second entry of sleep data which is going to from the previous day to this one
    sleep_data_response = whoop_client.get_sleep_collection(start_date=cycle_date, end_date=cycle_date)

    if len(sleep_data_response) < 2:
        sleep_data = sleep_data_response[0]
        sleep_duration_milli = sleep_data["score"]["stage_summary"]["total_light_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_rem_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_slow_wave_sleep_time_milli"]
        sleep_time = datetime.datetime.strptime(sleep_data["start"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%H:%M")
        wake_time = datetime.datetime.strptime(sleep_data["end"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%H:%M")
        seconds, milliseconds = divmod(sleep_duration_milli, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        sleep_duration = datetime.time(hour=hours, minute=minutes, second=seconds).strftime("%H:%M")
        sleep_efficiency = round(sleep_data["score"]["sleep_efficiency_percentage"]) / 100

    elif len(sleep_data_response) == 0:
        sleep_efficiency = ""
        sleep_duration = ""
        sleep_time = ""
        wake_time = ""

    else:
        sleep_data = sleep_data_response[1]
        sleep_duration_milli = sleep_data["score"]["stage_summary"]["total_light_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_rem_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_slow_wave_sleep_time_milli"]
        sleep_time = datetime.datetime.strptime(sleep_data["start"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%H:%M")
        wake_time = datetime.datetime.strptime(sleep_data["end"], "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%H:%M")
        seconds, milliseconds = divmod(sleep_duration_milli, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        sleep_duration = datetime.time(hour=hours, minute=minutes, second=seconds).strftime("%H:%M")
        sleep_efficiency = round(sleep_data["score"]["sleep_efficiency_percentage"]) / 100

    # Recovery
    recovery_data_response = whoop_client.get_recovery_collection(start_date=cycle_date, end_date=cycle_date)

    if len(recovery_data_response) < 2:
        recovery_data = recovery_data_response[0]
        hrv = round(recovery_data["score"]["hrv_rmssd_milli"])
        rhr = round(recovery_data["score"]["resting_heart_rate"])
        recovery = round(recovery_data["score"]["recovery_score"])
    elif len(recovery_data_response) == 0:
        hrv = ""
        rhr = ""
        recovery = ""
    else:
        recovery_data = recovery_data_response[1]
        hrv = round(recovery_data["score"]["hrv_rmssd_milli"])
        rhr = round(recovery_data["score"]["resting_heart_rate"])
        recovery = round(recovery_data["score"]["recovery_score"])


    # Strain
    workouts_data_response = whoop_client.get_cycle_collection(start_date=cycle_date, end_date=cycle_date)

    if len(workouts_data_response) < 2:
        strain = round(workouts_data_response[0]["score"]["strain"], 1)
    elif len(workouts_data_response) == 0:
        strain = ""
    else:
        strain = round(workouts_data_response[1]["score"]["strain"], 1)

    return {
        "sleep_efficiency": sleep_efficiency,
        "sleep_duration": sleep_duration,
        "sleep_time": sleep_time,
        "wake_time": wake_time,
        "HRV": hrv,
        "RHR": rhr,
        "recovery": recovery,
        "strain": strain
    }


def run():
    # Check if the config file exists
    generated_config = False

    if not os.path.isfile(INI):
        print("Config file not found, creating a template")
        shutil.copy(TEMPLATE_INI, INI)
        print("Please fill out the config file and run again")

    # Check if the spreadsheet map exists
    if not os.path.isfile(SPREADSHEET_MAP):
        print("Spreadsheet map not found, creating a template")
        shutil.copy(SPREADSHEET_MAP_TEMPLATE, SPREADSHEET_MAP)
        print("Please fill out / review the spreadsheet map and run again")

    if generated_config:
        sys.exit(1)

    # Get values from config file
    config = configparser.ConfigParser()
    config.read(INI)

    whoop_enabled = False
    myfitnesspal_enabled = False

    if config["whoop"]["enabled"] == "1":
        whoop_enabled = True

    if config["mfp"]["enabled"] == "1":
        myfitnesspal_enabled = True

    # Fail early if no services are enabled
    if not whoop_enabled and not myfitnesspal_enabled:
        logging.error("No services enabled in config file")
        sys.exit(1)

    start_date = config["general"]["start_date"]
    start_week = config["general"]["start_week"]

    # Google Sheets
    spreadsheet_mapping = json.load(open(config["gsheet"]["json"], "r"))
    gc = gspread.service_account(config["gsheet"]["creds"])
    sheet = gc.open_by_url(config["gsheet"]["url"])

    # Whoop
    if whoop_enabled:
        whoop_username = config["whoop"]["username"]
        whoop_password = config["whoop"]["password"]

        if not whoop_username:
            print("Whoop username not set in config")
            whoop_username = input("Enter your whoop username: ")

        if not whoop_password:
            print("Whoop password not set in config")
            whoop_password = getpass.getpass("Enter your whoop password: ")

        # Setup whoop client
        whoop_client = WhoopClient(whoop_username, whoop_password)

    # MyFitnessPal
    # Get cookies from chrome for myfitnesspal
    if myfitnesspal_enabled:
        myfitnesspal_cookies = get_browser_cookies(config["mfp"]["browser"], "myfitnesspal.com")
        myfitnesspal_login = myfitnesspal.Client(myfitnesspal_cookies)

    # convert start_date to datetime
    current_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()

    week = int(start_week) - 1
    cells_to_update = []

    while True:
        week += 1
        time.sleep(0.75)  # Prevents rate limiting

        # Attempt to open the week tab
        try:
            tab = sheet.worksheet(f"Week {week}")
        except gspread.exceptions.WorksheetNotFound:
            logging.error(f"Could not find tab for week {week} - stopping")
            break

        # Check if this spreadsheet is completed, if so move on
        if tab.acell(spreadsheet_mapping["complete"]).value == "Y":
            logging.info("Week %s is already complete, moving on", week)

            # Increment the date by 7 days
            current_date += timedelta(days=7)
            continue

        logging.info("Processing week %s", week)
        for day in range(1, 8):  # Each day of the week which is used to map to co-ord in mapping sheet
            week_day = current_date.strftime("%A")
            output_date = current_date.strftime("%Y-%m-%d")
            logging.info(f"Processing day {output_date} - {week_day}")

            # Get the data from whoop
            if whoop_enabled:
                whoop_data = get_whoop_day_data(whoop_client, current_date)
                for entry in whoop_data:
                    try:
                        coord = spreadsheet_mapping[str(day)][0]["whoop"][entry]
                    except KeyError:
                        logging.error(f"Could not find coordinate for {entry} on day {day}")
                        continue

                    # tab.update(coord, whoop_data[entry])
                    cells_to_update.append(create_cell(coord, whoop_data[entry]))

            # Get the data from myfitnesspal
            if myfitnesspal_enabled:
                mfp_data = get_mfp_day_data(myfitnesspal_login, current_date)
                for entry in mfp_data:
                    try:
                        coord = spreadsheet_mapping[str(day)][0]["mfp"][entry]
                    except KeyError:
                        logging.error(f"Could not find coordinate for {entry} on day {day}")
                        continue

                    if entry == "water":
                        mfp_data[entry] = round(float(mfp_data[entry]) / 1000, 2)

                    #tab.update(coord, mfp_data[entry])
                    cells_to_update.append(create_cell(coord, mfp_data[entry]))

            # Next day
            current_date += timedelta(days=1)

        # Update the spreadsheet for this week
        tab.update_cells(cells_to_update)

if __name__ == '__main__':
    run()

