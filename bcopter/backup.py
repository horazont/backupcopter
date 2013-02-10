import logging
import os
import subprocess

from . import shift
from . import device_context

logger = logging.getLogger(__name__)

def initialize_btrfs(ctx):
    subvolumes = {}
    sv_dest = ctx.base.source_btrfs_snapshotdir
    if not sv_dest:
        logger.info("no btrfs subvolumes configured")
        return subvolumes
    if not ctx.isdir(sv_dest):
        os.makedirs(sv_dest)
    try:
        with device_context.DirectoryContext(ctx, sv_dest):
            for sv_root in ctx.base.source_btrfs_volumes:
                sv_name = sv_root.replace("/", "__")
                logger.info("creating snapshot of %s", sv_root)
                ctx.check_call(["btrfs", "subvolume", "snapshot", "-r", sv_root, sv_name])
                subvolumes[sv_root] = os.path.join(sv_dest, sv_name)
    except:
        finalize_btrfs(ctx, subvolumes)

    return subvolumes

def finalize_btrfs(ctx, subvolumes):
    for sv_path in subvolumes.values():
        ctx.check_call(["btrfs", "subvolume", "delete", sv_path])

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
        self.ctx.rsync(self.target, self.source, self.dest, self.linkdest)

    def __exit__(self, *exc_info):
        if exc_info[0] is not None:
            logger.warn("error during transaction, rolling back (see below for traceback)")
            self.ctx.deltree(self.dest)
            if self.linkdest is not None:
                self.ctx.cp_al(self.linkdest, self.dest)

def do_backup(ctx, interval):
    target_dir = shift.interval_dirname(interval, 0)
    indicies = shift.interval_indicies(interval)
    indicies.sort()
    try:
        del indicies[0]
        next_index = indicies.pop(0)[0]
    except (ValueError, IndexError):
        linkdest_dir = None
    else:
        linkdest_dir = shift.interval_dirname(interval, next_index)

    logger.info("initializing source btrfs subvolumes (if any)")
    subvolumes = initialize_btrfs(ctx)
    try:
        ctx._dryrun = False
        try:
            for target in ctx.targets:
                logger.info("backing up %s", target)
                source = target.source_prefix + target.source
                if target.local:
                    source = substitute_btrfs_snapshot(subvolumes, source)
                dest = os.path.join(target_dir, target.dest)
                if not os.path.isdir(dest):
                    os.makedirs(dest)
                linkdest = os.path.abspath(os.path.join(linkdest_dir, target.dest))
                if not ctx.isdir(linkdest):
                    linkdest = None
                try:
                    with BackupTransaction(ctx, target, source, dest, linkdest) as transaction:
                        transaction.execute()
                except subprocess.CalledProcessError as err:
                    logging.exception(err)
        finally:
            ctx._dryrun = False
    finally:
        finalize_btrfs(ctx, subvolumes)
