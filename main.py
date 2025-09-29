from datetime import timedelta
from zoneinfo import ZoneInfo
from itertools import count

from whoopy import WhoopClient
from whoopy.models.models_v2 import Sleep, Cycle
from whoopy.exceptions import RefreshTokenError
from gspread.cell import Cell
from gspread.utils import a1_to_rowcol
from whoopy.exceptions import ResourceNotFoundError

import whoopy
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
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WHOOP_CREDS_FILE_TMP = "whoop_credentials.json"
WHOOP_CONFIG_FILE_TMP = "config.json"
WHOOP_CONFIG_TEMPLATE = "config.json.template"
WHOOP_CREDS_FILE = os.path.join(SCRIPT_DIR, WHOOP_CREDS_FILE_TMP)
WHOOP_CONFIG_FILE = os.path.join(SCRIPT_DIR, WHOOP_CONFIG_FILE_TMP)


def convert_utc_to_local(utc_datetime: datetime.datetime, timezone_str: str) -> str:
    """
    Converts a UTC time string to a local time string.
    :param time_str:
    :param timezone_str:
    :return:
    """
    #TODO remove utc_dt = datetime.datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=ZoneInfo("UTC"))
    local_dt = utc_datetime.astimezone(ZoneInfo(timezone_str))
    return local_dt.strftime("%H:%M")


def try_get_recovery_for_cycle_id(client, cid):
    try:
        rec = client.recovery.get_for_cycle(cid)
        return rec if getattr(rec, "score", None) else None
    except ResourceNotFoundError:
        return None

def get_sleep_duration(sleep_data: Sleep) -> str:
    """
    Get the exact sleep total from sleep data

    :param sleep_data:
    :return: stru
    """
    sleep_duration_milli = sleep_data.score.stage_summary.total_light_sleep_time_milli + \
                           sleep_data.score.stage_summary.total_slow_wave_sleep_time_milli + \
                           sleep_data.score.stage_summary.total_rem_sleep_time_milli
    seconds, milliseconds = divmod(sleep_duration_milli, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    return f"{hours:02}:{minutes:02}"

def get_datestamp(dt: datetime.datetime):
    return dt.strftime("%Y-%m-%d")

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


def get_whoop_day_data(whoop_client: whoopy.WhoopClient, date, timezone):
    # Correct timezone
    naive_dt = datetime.datetime.combine(date, datetime.time(12, 0))
    local_dt = naive_dt.replace(tzinfo=ZoneInfo(timezone))
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))

    # Work out the correct cycle dates

    # TODO there's a bug in here that actualy gets the day before in some cases. Noteaby the earlier the time the more
    # TODO likely this is to happen it seems
    window_start = utc_dt - timedelta(days=1)
    window_end = utc_dt + timedelta(days=1)
    cycles = whoop_client.cycles.get_all(start=window_start, end=window_end)

    target_cycle: Cycle = None
    for c in cycles:
        try:
            if c.start <= utc_dt <= c.end:
                target_cycle = c
                break
        except Exception:
            pass
    if not target_cycle and cycles:
        # Fallback: most recent in the window
        target_cycle = cycles[-1]

    # Sleep
    # Get second entry of sleep data which is going to from the previous day to this one
    sleep_data_response = whoop_client.sleep.get_all(start=utc_dt - timedelta(days=1), end=utc_dt)

    if len(sleep_data_response) == 0:
        sleep_efficiency = WHOOP_ERROR
        sleep_duration = WHOOP_ERROR
        sleep_time = WHOOP_ERROR
        wake_time = WHOOP_ERROR

    elif len(sleep_data_response) == 1:
        sleep_data = sleep_data_response[0]

        if not sleep_data.score:
            sleep_duration = get_sleep_duration(sleep_data)
            sleep_efficiency = WHOOP_ERROR
        else:
            sleep_duration = get_sleep_duration(sleep_data)
            sleep_efficiency = sleep_data.score.sleep_efficiency_percentage

        sleep_time = convert_utc_to_local(sleep_data.start, timezone)
        wake_time = convert_utc_to_local(sleep_data.end, timezone)

    else:
        # TODO should search the responses for naps and things and remove those until a sleep remains
        # Potentially right at the start of this if chain
        sleep_data = sleep_data_response[1]

        if not sleep_data.score:
            sleep_duration = get_sleep_duration(sleep_data)
            sleep_efficiency = WHOOP_ERROR

        else:
            sleep_duration = get_sleep_duration(sleep_data)
            sleep_efficiency = sleep_data_response.score.sleep_efficiency_percentage

        sleep_time = convert_utc_to_local(sleep_data.start, timezone)
        wake_time = convert_utc_to_local(sleep_data.end, timezone)

    # Strain
    day_strain = ""
    try:
        if target_cycle and target_cycle.score and target_cycle.score.strain is not None:
            day_strain = round(target_cycle.score.strain, 1)
    except Exception:
        logging.info(f"Failed to get day strain for {get_datestamp(local_dt)}")
        day_strain = WHOOP_ERROR

    # Recovery
    rec = whoop_client.recovery.get_for_cycle(target_cycle.id)

    if rec:
        hrv = round(rec.score.hrv_rmssd_milli)
        rhr = round(rec.score.resting_heart_rate)
        recovery = round(rec.score.recovery_score)
    else:
        logging.info(f"Failed to get recovery scores for {get_datestamp(local_dt)}")
        hrv = rhr = recovery = WHOOP_ERROR

    return {
        "sleep_efficiency": f"{round(sleep_efficiency)}%",
        "sleep_duration": sleep_duration,
        "sleep_time": sleep_time,
        "wake_time": wake_time,
        "HRV": hrv,
        "RHR": rhr,
        "recovery": recovery,
        "strain": day_strain
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
    whoop_client = None
    if whoop_enabled:
        if os.path.exists(WHOOP_CREDS_FILE):
            with open(WHOOP_CREDS_FILE, 'r') as f:
                whoop_creds = json.load(f)

            with open(WHOOP_CONFIG_FILE_TMP, 'r') as f:
                whoop_config = json.load(f)

            whoop_client: WhoopClient = WhoopClient.from_token(
                access_token=whoop_creds["access_token"],
                refresh_token=whoop_creds["refresh_token"],
                client_id=whoop_config["client_id"],
                client_secret=whoop_config["client_secret"]
            )

            try:
                whoop_client.user.get_profile()
            except RefreshTokenError:
                os.remove(WHOOP_CREDS_FILE)
                whoop_client = None
        else:
            if not os.path.exists(WHOOP_CONFIG_FILE):
                shutil.copy(WHOOP_CONFIG_TEMPLATE, WHOOP_CONFIG_FILE_TMP)

        if not whoop_client:
            with open(WHOOP_CONFIG_FILE_TMP, 'r') as f:
                whoop_config = json.load(f)

            whoop_client = WhoopClient.auth_flow(
                client_id=whoop_config["client_id"],
                client_secret=whoop_config["client_secret"],
                redirect_uri=whoop_config["redirect_uri"]
            )

            whoop_client.save_token(WHOOP_CREDS_FILE)

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

    whoop_client.close()

if __name__ == '__main__':
    run()

