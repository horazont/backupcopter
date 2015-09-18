import contextlib
import logging
import os
import subprocess

from . import shift
from . import device_context
from . import command

logger = logging.getLogger(__name__)

def initialize_btrfs(ctx):
    subvolumes = {}
    sv_dest = ctx.base.source_btrfs_snapshotdir
    if not sv_dest:
        logger.debug("no btrfs subvolumes configured")
        return subvolumes
    if not ctx.isdir(sv_dest):
        os.makedirs(sv_dest)
    try:
        with device_context.DirectoryContext(ctx, sv_dest):
            for sv_root in ctx.base.source_btrfs_volumes:
                sv_name = sv_root.replace("/", "__")
                if os.path.isdir(sv_name):
                    logger.info("deleting old subvolume at %s", sv_name)
                    ctx.check_call(["btrfs", "subvolume", "delete", sv_name])
                logger.info("creating snapshot of %s", sv_root)
                ctx.check_call(["btrfs", "subvolume", "snapshot", "-r", sv_root, sv_name])
                subvolumes[sv_root] = os.path.join(sv_dest, sv_name)
    except:
        finalize_btrfs(ctx, subvolumes)

    return subvolumes

def finalize_btrfs(ctx, subvolumes):
    for sv_path in subvolumes.values():
        try:
            ctx.check_call(["btrfs", "subvolume", "delete", sv_path])
        except subprocess.CalledProcessError:
            logger.warn("could not delete subvolume: %s", sv_path)

def substitute_btrfs_snapshot(subvolumes, source_path):
    longest_match = None
    substitute = None
    for sv_root, sv_new_root in subvolumes.items():
        if source_path.startswith(sv_root):
            if longest_match is None or len(sv_root) > len(longest_match):
                longest_match = sv_root
                substitute = sv_new_root

    if longest_match is None:
        return source_path

    new_path = source_path[len(longest_match):]
    if new_path.startswith("/"):
        new_path = new_path[1:]
    new_path = os.path.join(substitute, new_path)
    logging.debug("snapshot substitution: %s => %s", source_path, new_path)
    return new_path

class BackupTransaction:
    def __init__(self, ctx, target, source, dest, linkdest):
        self.ctx = ctx
        self.target = target
        self.source = source
        self.dest = dest
        self.linkdest = linkdest

    def __enter__(self):
        return self

    def execute(self):
        if self.linkdest is not None and not self.ctx.base.rsync_linkdest:
            logging.warn("no rsync --link-dest, I'm going to use cp -al for bootstrapping")
            self.ctx.cp_al(self.linkdest, self.dest)

        additional_args = []
        if self.target.exclude_from_incremental:
            for item in self.target.exclude_from_incremental:
                additional_args.append("--exclude")
                additional_args.append(item)

        self.ctx.rsync(self.target, self.source, self.dest, self.linkdest,
                       additional_args=additional_args)

        if self.target.exclude_from_incremental:
            non_incremental_args = ["--delete"]
            non_incremental_dir = os.path.join("non-incremental",
                                               self.target.dest)
            for item in self.target.exclude_from_incremental:
                path = item[1:]
                dest = os.path.join(non_incremental_dir,
                                    path)
                parent = os.path.dirname(dest)
                if not os.path.isdir(parent):
                    try:
                        os.makedirs(parent)
                    except FileExistsError:
                        # type has changed...?
                        self.ctx.deltree(parent)
                        os.makedirs(parent)
                source = os.path.join(self.source, path)
                if os.path.isdir(dest) != os.path.isdir(source):
                    # type has changed
                    self.ctx.deltree(dest)

                if os.path.isdir(source):
                    source += "/"
                    dest += "/"

                self.ctx.rsync(
                    self.target,
                    source,
                    dest,
                    linkdest=None,
                    additional_args=non_incremental_args)


    def __exit__(self, *exc_info):
        if exc_info[0] is not None:
            logger.warn("error during transaction, rolling back (see below for traceback)")
            self.ctx.deltree(self.dest)
            if self.linkdest is not None:
                self.ctx.cp_al(self.linkdest, self.dest)

class CmdBackup(command.ConfigurableMountCommand):
    def __init__(self, **kwargs):
        super().__init__(umount_default=True, **kwargs)

    def get_info(self):
        return command.CommandInfo(
            command="backup",
            description="Run a backup"
        )

    def setup_parser(self, parser):
        super().setup_parser(parser)
        parser.add_argument(
            "intervals",
            metavar="INTERVAL",
            nargs="+",
            help="The set of backup intervals to run"
        )

        parser.epilog = \
        """
        This will make a backup of the smallest interval specified. If the
        amount of backups in this interval is currently equal to the maximum
        configured amount, the oldest backup from this interval is deleted
        before the backup is started.

        The larger intervals are handled by creating a hard-linked copy to the
        backup of the smallest interval. This provides perfectly aligned backups
        by specifying all intervals which currently apply.
        """

    def run(self, args, conf):
        try:
            args.intervals.sort(
                key=conf.base.intervals.index,
                reverse=True
            )
        except ValueError as err:
            logger.error("Unknown interval specified: %s", err)
            return 3

        with device_context.DeviceContext(conf, args):
            backup_interval = args.intervals.pop()
            shift.do_shift(conf, backup_interval)
            if     (not conf.base.intervals_run_only_lowest or
                    conf.base.intervals.index(backup_interval) == 0):
                # either we allow all intervals to create a root backup
                # (intervals_run_only_lowest is False) or the lowest interval
                # specified at CLI must be the lowest interval
                # configured. otherwise, don’t run a backup.
                do_backup(conf, backup_interval)
            else:
                logger.warn("Nothing to do (%s is not the lowest interval "
                            "configured).", backup_interval)
                args.intervals.append(backup_interval)

            for other_interval in args.intervals:
                shift.do_shift(conf, other_interval)
            shift.clone_intervals(conf, backup_interval, args.intervals)

def do_backup(ctx, interval):
    target_dir = shift.interval_dirname(interval, 0)
    indicies = shift.interval_indicies(interval)
    indicies.sort()
    try:
        next_index = indicies.pop(0)[0]
    except (ValueError, IndexError):
        linkdest_dir = None
    else:
        linkdest_dir = shift.interval_dirname(interval, next_index)

    subvolumes = initialize_btrfs(ctx)
    try:
        for target in ctx.targets:
            logger.info("backing up %s", target)
            source = target.source_prefix + target.source
            if target.local:
                source = substitute_btrfs_snapshot(subvolumes, source)
            dest = os.path.join(target_dir, target.dest)
            if not os.path.isdir(dest):
                os.makedirs(dest)
            if linkdest_dir is not None:
                linkdest = os.path.abspath(
                    os.path.join(linkdest_dir, target.dest))
                if not ctx.isdir(linkdest):
                    linkdest = None
            else:
                linkdest = None
            try:
                with BackupTransaction(ctx, target, source, dest, linkdest) as transaction:
                    transaction.execute()
            except subprocess.CalledProcessError as err:
                logging.exception(err)
    finally:
        finalize_btrfs(ctx, subvolumes)
