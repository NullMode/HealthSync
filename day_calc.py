import argparse
import datetime

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Work out your day 1 start date working backwards from the current week")
    parser.add_argument("--date", help="the date of day 7 in the spreadsheet", type=str)
    parser.add_argument("--week", help="the current week in tracking sheet", type=int)
    args = parser.parse_args()

    date = datetime.datetime.strptime(args.date, "%Y-%m-%d")

    # For each week number working backwards
    for week in range(args.week, 0, -1):
        for day in range(7, 0, -1):
            # Print the current date before subtracting
            day_name = date.strftime('%A')
            print(f"Week {week} - Day {day}: {day_name} - {date.strftime('%Y-%m-%d')}")

            # Subtract one day for the next iteration
            date -= datetime.timedelta(days=1)
        print("")