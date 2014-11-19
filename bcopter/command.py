import abc
import collections

_CommandInfo = collections.namedtuple(
    "_CommandInfo",
    [
        "command",
        "description",
        "need_config",
    ])

class CommandInfo(_CommandInfo):
    def __new__(cls, command, description, *, need_config=True, **kwargs):
        obj = super(CommandInfo, cls).__new__(
            cls,
            command,
            description,
            need_config,
            **kwargs)
        return obj

del _CommandInfo

class Command(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_info(self):
        """
        Return information on the command. The information is used to register
        the command with the argument parser.

        The method must return a :class:`CommandInfo` object.
        """

    @abc.abstractmethod
    def setup_parser(self, parser):
        """
        Set up the supplied :class:`argparse.ArgumentParser` instance *parser*
        for use with this command.
        """

    @abc.abstractmethod
    def run(self, args, conf):
        """
        Run the command. *args* is the namespace returned by the argument
        parser. *conf* is the :class:`bcopter.Context` instance created from
        loading the supplied configuration.
        """

class CmdHelpConfig(Command):
    def get_info(self):
        return CommandInfo(
            command="help-config",
            description="Print a reference on the options supported in the "
            "config files. The use of a pager (e.g. less) is recommended."
        )

    def setup_parser(self, parser):
        pass

    def run(self, args, conf):
        import bcopter.config
        bcopter.config.print_config_options()
        return 0

class CmdDumpConfig(Command):
    def get_info(self):
        return CommandInfo(
            command="dump-config",
            description="Print the current configuration to stdout."
        )

    def setup_parser(self, parser):
        pass

    def run(self, args, conf):
        conf.dump()
        return 0

class ConfigurableMountCommand(Command):
    def __init__(self, *, umount_default=False, **kwargs):
        super().__init__(**kwargs)
        self._umount_default = umount_default

    def setup_parser(self, parser):
        super().setup_parser(parser)

        if self._umount_default:
            description = "The default for this command is --umount."
        else:
            description = "The default for this command is --no-umount."

        group = parser.add_argument_group(
            title="Mounting options",
            description=description
        )

        mutex_group = group.add_mutually_exclusive_group()

        arg = mutex_group.add_argument(
            "--no-umount",
            action="store_false",
            dest="umount",
            default=self._umount_default,
            help="Do not unmount the backup device, even if it has been "
            "mounted by this command. This is useful when running several "
            "backup-related commands in series."
        )

        if not self._umount_default:
            arg.help += " This is the default for this command."

        arg = mutex_group.add_argument(
            "--umount",
            action="store_true",
            dest="umount",
            help="Always unmount the backup device, if it has been mounted"
            " by this command."
        )

        if self._umount_default:
            arg.help += " This is the default for this command."

        group.add_argument(
            "--force-umount",
            action="store_true",
            dest="force_umount",
            default=False,
            help="Always unmount (and possibly put to sleep) the backup device,"
            " even if it has not been mounted by this command. Implies "
            "--umount."
        )
