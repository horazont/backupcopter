import logging
import os
import stat
import subprocess
import sys
import shlex

logger = logging.getLogger("context")

from . import config

class NullProcess:
    stdin = None
    stdout = None
    stderr = None
    pid = None
    returncode = 0

    def __init__(self, args, **kwargs):
        super().__init__()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def send_signal(self, signal):
        pass

    def terminate(self):
        pass

    def kill(self):
        pass

class LoggedProcess:
    logger = logging.getLogger("cmd")

    @staticmethod
    def _format_command(command):
        s = command[0] + " "
        s += " ".join(map(shlex.quote, command[1:]))
        return s

    @classmethod
    def _raise_process_error(cls, returncode, args):
        raise subprocess.CalledProcessError(
            returncode, cls._format_command(args))

    @classmethod
    def check_call(cls, dry_run, args, *,
                   stdin=None, stdout=None, stderr=None, shell=False,
                   timeout=None):
        proc = cls(
            dry_run, args,
            stdin=stdin, stdout=stdout, stderr=stderr, shell=shell)
        returncode = proc.wait(timeout=timeout)
        if returncode != 0:
            cls._raise_process_error(returncode, args)

    @classmethod
    def check_output(cls, dry_run, args, *,
                     stdin=None, stderr=None, shell=False,
                     universal_newlines=False, timeout=None):
        if dry_run:
            raise NotImplementedError("There is no sane implementation of check_output in dry-run mode.")
        proc = cls(
            dry_run, args,
            stdout=subprocess.PIPE,
            stdin=stdin, stderr=stderr, shell=shell,
            universal_newlines=universal_newlines)
        stdout, _ = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            cls._raise_process_error(proc.returncode, args)
        return stdout

    def __new__(cls, dry_run, args, *further_args, **kwargs):
        if dry_run:
            cls.logger.log(
                logging.DRYRUN, "executing: %s", cls._format_command(args))
            return NullProcess(args, *further_args, **kwargs)
        else:
            cls.logger.debug(
                "executing: %s", cls._format_command(args))
            return subprocess.Popen(args, *further_args, **kwargs)

    def __init__(self, dry_run, args, *further_args, **kwargs):
        assert False


class Context(config.Config):
    """
    This class maintains the configuration of the backup tool and
    imposes the operating system interface. This is also where the
    dry-mode is implemented, by just intercepting most calls.
    """

    def __init__(self, dryrun):
        super().__init__()
        self._dryrun = dryrun
        if self._dryrun:
            logging.log(logging.DRYRUN, "Running in dry-run mode")

    def check_call(self, command, *args, **kwargs):
        return LoggedProcess.check_call(
            self._dryrun, command, *args, **kwargs)

    def check_output(self, command, *args, **kwargs):
        return LoggedProcess.check_output(
            self._dryrun, command, *args, **kwargs)

    def Popen(self, command, *args, **kwargs):
        return LoggedProcess(
            self._dryrun, command, *args, **kwargs)

    def deltree(self, path):
        if self.base.rm_cmd:
            self.check_call([self.base.rm_cmd, "-rf", path])
        else:
            if not self._dryrun:
                import shutil
                shutil.rmtree(path)

    def rename(self, oldname, newname):
        if not self._dryrun:
            os.rename(oldname, newname)

    def isdir(self, path):
        return os.path.isdir(path)

    def chdir(self, path):
        os.chdir(path)

    def isdev(self, path):
        try:
            statinfo = os.stat(path)
        except FileNotFoundError:
            return False
        return stat.S_ISBLK(statinfo.st_mode)

    def _construct_cp_al(self, source, dest):
        return [self.base.cp_cmd, "-al", source, dest]

    def _require_cp_al(self):
        raise NotImplementedError("We don't support missing cp right now.")

    def cp_al(self, source, dest):
        if self.base.cp_cmd:
            self.check_call(self._construct_cp_al(source, dest))
        elif not self._dryrun:
            self._require_cp_al()

    def cp_al_async(self, source, dest):
        if self.base.cp_cmd:
            return self.Popen(self._construct_cp_al(source, dest))
        elif not self._dryrun:
            self._require_cp_al()

    def wrap_ssh_command(self, target, command):
        """
        If the target asks for trickle, we'll wrap the ssh command accordingly.
        """
        if not target.trickle_enable:
            return command
        else:
            new_command = [
                self.base.trickle_cmd,
                "-d",
                str(target.trickle_downstream_limit),
                "-u",
                str(target.trickle_upstream_limit),
                ]
            if target.trickle_standalone:
                new_command.insert(1, "-s")
            new_command.extend(command)
            return new_command

    def rsync(self, target, source, dest, linkdest=None, additional_args=[]):
        """
        Call rsync for *target* to sync files from *source* to *dest*,
        optionally using *linkdest* as argument to `--link-dest` (see
        rsync manual for details). The caller has to ensure that
        linkdest has been enabled in the configuration if the call
        depends on it to work. This method will silently drop the
        request if linkdest has not been enabled.

        Composes the rsync call taking into account the rate limiting
        technologies picked and credentials given for the *target*.

        This will raise :cls:`subprocess.CalledProcessError` if rsync fails.
        """
        args = list(self.base.rsync_args)
        args.extend(["-r", source, dest])
        if self.base.rsync_linkdest and linkdest is not None:
            args.insert(0, "--link-dest")
            args.insert(1, linkdest)
        if self.base.rsync_onefs:
            args.insert(0, "-x")
        if not target.local:
            args.insert(0, "-e")
            ssh_call = [self.base.ssh_cmd]
            if target.ssh_port is not None:
                ssh_call.append("-p"+str(target.ssh_port))
            if target.ssh_identity is not None:
                ssh_call.append("-i"+target.ssh_identity)
            ssh_call = self.wrap_ssh_command(target, ssh_call)
            args.insert(1, " ".join(map(shlex.quote, ssh_call)))
            if self.base.rsync_args_remote:
                args.extend(self.base.rsync_args_remote)

        args.extend(additional_args)

        args.insert(0, "rsync")
        if target.ionice_enable:
            ionice_call = [self.base.ionice_cmd,
                           "-c", str(target.ionice_class),
                           "-n", str(target.ionice_level)]
            args = ionice_call + args
        try:
            self.check_call(args)
        except subprocess.CalledProcessError as err:
            # ignore and only warn about partial transfer errors
            if err.returncode in [23, 24]:
                logging.warn("Partial transfer occured -- continuing with other targets")
            else:
                logging.warn("Transfer failed with returncode {}".format(err.returncode))
                raise

    def warn_user(self, message):
        """
        Show an X11 notification with the given *message*. This should
        be used sparingly and requires root access or will prompt for
        a password.

        It _is_ used by the waiting context to notify the user if the
        backup device is not present.
        """
        new_env = dict(os.environ)
        if not "DISPLAY" in new_env:
            new_env["DISPLAY"] = ":0"
        self.check_call(["su", self.base.usertowarn, "-c",
                         "notify-send --urgency=critical --icon=dialog-warning-symbolic --expire-time=30000 \"Backup problem\" \"{}\"".format(message)])

    def device_missing(self, since, remaining):
        """
        Post a warning message to the user on the first time the
        waiting context complains about a missing device.
        """
        if since == 0:
            self.warn_user("Backup device not available. Please plug it in within {} seconds".format(remaining))
