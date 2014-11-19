import argparse
import sys
import logging
import os
import subprocess
import stat
import shlex

logging.basicConfig(
    level=logging.DEBUG,
    format='{0}:%(levelname)-8s %(message)s'.format(
        os.path.basename(sys.argv[0]))
)

logging.addLevelName(100, "DRYRUN")
logging.DRYRUN = 100

from . import context

DEFAULT_CONFIG_FILE = "/etc/backupcopter.conf"

logger = logging.getLogger()

class BackupCopter:
    def __init__(self):
        super().__init__()

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-c", "--config-file",
            metavar="CONFIGFILE",
            help="Path to a configuration file for backupcopter. Defaults to {}".format(DEFAULT_CONFIG_FILE),
            default="/etc/backupcopter.conf"
        )
        parser.add_argument(
            "-d", "--dry-run",
            action="store_true",
            default=False,
            help="If set, nothing will be done. Instead, all executed commands are printed on stdout and assumed to succeed immediately. EXPERIMENTAL"
        )
        parser.add_argument(
            "-v",
            action="count",
            default=0,
            help="Increase verbosity",
            dest="verbosity"
        )

        self._argparse = parser
        self._commands_parser = parser.add_subparsers(
            title="Subcommands",
            description="Backupcopter supports several commands. To do something"
            " meaningful you need to choose one."
        )

        self.args = None
        self.conf = None

    def load_config(self):
        with open(self.args.config_file, "r") as f:
            errors = self.conf.load(f, raise_on_error=False)

        if errors:
            exc = ValueError("fatal configuration errors, see log for details")
            logger.critical(str(exc))
            for error in errors:
                logger.error(str(error))

            raise exc

    def register_command(self, command):
        info = command.get_info()
        parser = self._commands_parser.add_parser(
            info.command,
            help=info.description)
        command.setup_parser(parser)
        parser.set_defaults(subcommand=(info, command))

    def prepare(self, argv=None):
        try:
            args = self._argparse.parse_args(args=argv)

            if not hasattr(args, "subcommand"):
                raise ValueError("No subcommand specified.")
        except (argparse.ArgumentError, ValueError) as err:
            self._argparse.print_help()
            print()
            sys.stdout.flush()
            logger.error(str(err))
            sys.stdout.flush()
            sys.stderr.flush()
            return False

        if args.verbosity >= 3:
            logging.getLogger().setLevel(logging.DEBUG)
        elif args.verbosity >= 2:
            logging.getLogger().setLevel(logging.INFO)
        elif args.verbosity >= 1:
            logging.getLogger().setLevel(logging.WARNING)
        else:
            logging.getLogger().setLevel(logging.ERROR)

        self.args = args
        self.conf = context.Context(self.args.dry_run)
        # print(self.args)
        return True

    def run(self):
        if self.args is None:
            self.prepare()

        cmd_info, cmd_obj = self.args.subcommand

        if cmd_info.need_config:
            self.load_config()

        returncode = cmd_obj.run(self.args, self.conf)
        if returncode is None:
            returncode = 0

        return returncode
