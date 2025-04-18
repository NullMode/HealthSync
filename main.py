from datetime import timedelta
from zoneinfo import ZoneInfo
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
WHOOP_ERROR = "N/A - Whoop Error"


def convert_utc_to_local(time_str: str, timezone_str: str) -> str:
    """
    Converts a UTC time string to a local time string.
    :param time_str:
    :param timezone_str:
    :return:
    """
    utc_dt = datetime.datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=ZoneInfo("UTC"))
    local_dt = utc_dt.astimezone(ZoneInfo(timezone_str))
    return local_dt.strftime("%H:%M")


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

        try:
            if stop or re.search('"has_more":(.*?),', page)[1] == 'false':
                break
        except TypeError:
            logging.error("Error getting information from mfp - you might need to authenticate again!")
            sys.exit(1)

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


def get_whoop_day_data(whoop_client, date, timezone):
    naive_dt = datetime.datetime.combine(date, datetime.time(12, 0))
    local_dt = naive_dt.replace(tzinfo=ZoneInfo(timezone))
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
    cycle_date = utc_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Sleep
    # Get second entry of sleep data which is going to from the previous day to this one
    sleep_data_response = whoop_client.get_sleep_collection(start_date=cycle_date, end_date=cycle_date)

    if len(sleep_data_response) == 0:
        sleep_efficiency = ""
        sleep_duration = ""
        sleep_time = ""
        wake_time = ""

    elif len(sleep_data_response) == 1:
        sleep_data = sleep_data_response[0]

        if not sleep_data["score"]:
            start = sleep_data["start"]
            end = sleep_data["end"]
            sleep_duration_time = datetime.datetime.strptime(end, "%Y-%m-%dT%H:%M:%S.%fZ") - datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%fZ")
            total_seconds = int(sleep_duration_time.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            sleep_duration = f"{hours:02}:{minutes:02}"
            sleep_efficiency = WHOOP_ERROR
        else:
            sleep_duration_milli = sleep_data["score"]["stage_summary"]["total_light_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_rem_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_slow_wave_sleep_time_milli"]
            seconds, milliseconds = divmod(sleep_duration_milli, 1000)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            sleep_duration = datetime.time(hour=hours, minute=minutes, second=seconds).strftime("%H:%M")
            sleep_efficiency = round(sleep_data["score"]["sleep_efficiency_percentage"]) / 100

        sleep_time = convert_utc_to_local(sleep_data["start"], timezone)
        wake_time = convert_utc_to_local(sleep_data["end"], timezone)

    else:
        sleep_data = sleep_data_response[1]

        if not sleep_data["score"]:
            start = sleep_data["start"]
            end = sleep_data["end"]
            sleep_duration_time = datetime.datetime.strptime(end, "%Y-%m-%dT%H:%M:%S.%fZ") - datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S.%fZ")
            total_seconds = int(sleep_duration_time.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            sleep_duration = f"{hours:02}:{minutes:02}"
            sleep_efficiency = WHOOP_ERROR

        else:
            sleep_duration_milli = sleep_data["score"]["stage_summary"]["total_light_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_rem_sleep_time_milli"] + sleep_data["score"]["stage_summary"]["total_slow_wave_sleep_time_milli"]
            seconds, milliseconds = divmod(sleep_duration_milli, 1000)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            sleep_duration = datetime.time(hour=hours, minute=minutes, second=seconds).strftime("%H:%M")
            sleep_efficiency = round(sleep_data["score"]["sleep_efficiency_percentage"]) / 100

        sleep_time = convert_utc_to_local(sleep_data["start"], timezone)
        wake_time = convert_utc_to_local(sleep_data["end"], timezone)

    # Recovery
    recovery_data_response = whoop_client.get_recovery_collection(start_date=cycle_date, end_date=cycle_date)

    if len(recovery_data_response) == 0:
        hrv = WHOOP_ERROR
        rhr = WHOOP_ERROR
        recovery = WHOOP_ERROR

    elif len(recovery_data_response) == 1:
        recovery_data = recovery_data_response[0]
        hrv = round(recovery_data["score"]["hrv_rmssd_milli"])
        rhr = round(recovery_data["score"]["resting_heart_rate"])
        recovery = round(recovery_data["score"]["recovery_score"])

    else:
        recovery_data = recovery_data_response[1]
        hrv = round(recovery_data["score"]["hrv_rmssd_milli"])
        rhr = round(recovery_data["score"]["resting_heart_rate"])
        recovery = round(recovery_data["score"]["recovery_score"])

    # Strain
    workouts_data_response = whoop_client.get_cycle_collection(start_date=cycle_date, end_date=cycle_date)

    if len(workouts_data_response) == 0:
        strain = ""

    if len(workouts_data_response) == 1:
        strain = round(workouts_data_response[0]["score"]["strain"], 1)

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
    timezone = config["general"]["timezone"]

    if not start_date:
        start_date = False
        logging.error("Start date not set in config")

    if not start_week:
        start_week = False
        logging.error("Start week not set in config")

    if not timezone:
        timezone = False
        logging.error("Timezone not set in config - should be in the format of 'Europe/London'")

    if not all([start_date, start_week, timezone]):
        sys.exit(1)

    try:
        start_week = int(start_week)
    except ValueError:
        logging.error("start_week must be an integer")
        sys.exit(1)

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

    week = 0  # Start at week 0 to allow for the loop logic to work
    cells_to_update = []
    reached_today = False

    # If start week is greater than, 1 fast forward to the current week
    if start_week > week + 1:
        logging.info("Start week is greater than current week, fast forwarding")
        for i in range(1, start_week):
            # Increment the date by 7 days
            current_date += timedelta(days=7)
            week += 1

    while True:
        week += 1
        time.sleep(0.75)  # Prevents rate limiting

        if reached_today:
            break

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
                whoop_data = get_whoop_day_data(whoop_client, current_date, timezone)
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

            if day < 8:
                # Next day
                current_date += timedelta(days=1)

                # If the next current date is greater than todays date stop
                if current_date > datetime.datetime.today().date():
                    reached_today = True
                    logging.info("Reached today's date, stopping")
                    break

        # Update the spreadsheet for this week
        tab.update_cells(cells_to_update)
        cells_to_update = []

        if reached_today:
            break


if __name__ == '__main__':
    run()

