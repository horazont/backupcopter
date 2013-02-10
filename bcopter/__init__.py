import argparse
import sys

from . import config

DEFAULT_CONFIG_FILE = "/etc/backupcopter.conf"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "intervals",
        metavar="INTERVAL",
        help="Any amount of intervals, as specified in the config. If no intervals are given, only a config check is made.",
        nargs="*"
    )
    parser.add_argument(
        "-c", "--config-file",
        metavar="CONFIGFILE",
        type=argparse.FileType("r"),
        help="Path to a configuration file for backupcopter. Defaults to {}".format(DEFAULT_CONFIG_FILE),
        default=None
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        default=False,
        help="If set, nothing will be done. Instead, all executed commands are printed on stdout and assumed to succeed immediately."
    )

    try:
        args = parser.parse_args()
    except argparse.ArgumentError as err:
        parser.print_help()
        print()
        sys.stdout.flush()
        print(str(err), file=sys.stderr)
        sys.stderr.flush()


    conf = config.Config()
    errors = conf.load("./config.ini", raise_on_error=False)
    if errors:
        print("fatal configuration errors found:")
        for error in errors:
            print(str(error))
        sys.exit(2)

    if not args.intervals:
        conf.dump()
        sys.exit(0)
