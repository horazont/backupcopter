#!/usr/bin/python3
import os
import sys

from datetime import datetime

fmt = "%Y-%m-%dT%H:%M:%S"

def dayofweek(dt):
    return dt.weekday()

def is_monthly(last, current):
    last = last.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    current = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    return last != current

def is_weekly(last, current):
    delay = current - last
    if delay.days >= 7:
        return True

    last_dow = dayofweek(last)
    current_dow = dayofweek(current)
    if last_dow == current_dow:
        return False

    # overflow
    if current_dow < last_dow:
        return True

    return False

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="""\
This utility can be used to run a daily command with special arguments when a
week or a month is over. For this, it uses a state file which stores the last
run. If a new week started since the last run, the value specified with the
``--monthly`` argument is appended to the command line to run. If a new month
started since the last run, the value specified with the ``--yearly`` argument
is appended to the command line to run.
"""
    )

    parser.add_argument(
        "--monthly",
        default="monthly",
        help="The argument to append if a new month has started since the last"
        " run (default: 'monthly')",
    )
    parser.add_argument(
        "--weekly",
        default="weekly",
        help="The argument to append if a new week has started since the last"
        " run (default: 'weekly')",
    )
    parser.add_argument(
        "-f", "--state-file",
        metavar="FILE",
        required=True,
        help="The state file to store the last run date in. If it does not"
        " exist, it is created and a normal run is started.",
    )
    parser.add_argument(
        "commandline",
        nargs="+",
        help="The command line to run"
    )

    args = parser.parse_args()

    try:
        with open(args.state_file, "r") as f:
            datetime_str = f.read().strip()
        last_run = datetime.strptime(datetime_str, fmt)
    except FileNotFoundError:
        last_run = None

    this_run = datetime.utcnow().replace(microsecond=0)
    if last_run is not None and this_run == last_run:
        print("last run is too recent", file=sys.stderr)
        sys.exit(1)

    with open(args.state_file, "w") as f:
        f.write(this_run.strftime(fmt))
        f.write("\n")

    if last_run is not None and is_weekly(last_run, this_run):
        args.commandline.append(args.weekly)

    if last_run is not None and is_monthly(last_run, this_run):
        args.commandline.append(args.monthly)

    os.execv(args.commandline[0], args.commandline)
