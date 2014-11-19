#!/usr/bin/python3

if __name__ == "__main__":
    import sys

    import bcopter
    import bcopter.command
    import bcopter.backup

    instance = bcopter.BackupCopter()

    instance.register_command(bcopter.command.CmdHelpConfig())
    instance.register_command(bcopter.command.CmdDumpConfig())
    instance.register_command(bcopter.backup.CmdBackup())

    if not instance.prepare():
        sys.exit(1)
    sys.exit(instance.run())
