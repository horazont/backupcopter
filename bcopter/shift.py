"""
In this file, the shifting and management of backup "intervals" is
handled. Remember that backupcopter itself does not know about
time. It only knows which backup intervals it is supposed to do at one
specific call.
"""
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

def interval_dirname(interval, index):
    """
    Create a interval directory name from a given *interval* name and
    a given *index*.
    """
    return interval + "." + str(index)

def interval_indicies(interval):
    """
    Inspect the interval directories in the current folder and extract
    those belonging to the given *interval*.

    Return a list of integer numbers corresponding to their indicies.
    """
    interval_folders = (
        (folder, folder.split(".", 1)[1]) for folder in os.listdir()
        if folder.startswith(interval+".")
    )

    indicies = []
    for dirname, index in interval_folders:
        try:
            index = int(index)
        except ValueError:
            logger.info("unknown folder: %s", dirname)
            continue
        indicies.append((index, dirname))
    return indicies

def do_shift(context, interval):
    """
    Shift directories belonging to one interval upwards, if the lowest index is
    in use. If there would be too many directories after shifting, the directory
    with the highest number is deleted *beforehands*.
    """
    indicies = interval_indicies(interval)
    indicies.sort(reverse=True)
    if not indicies or indicies[-1][0] != 0:
        # index 0 is free
        return

    logger.info("making room for new backup in interval \"%s\"", interval)
    my_depth = context.base.intervals_shiftdepth.get(interval, None)

    for index, dirname in indicies:
        if my_depth and index >= my_depth-1:
            logger.debug("removing surplus folder: %s", dirname)
            context.deltree(dirname)
        else:
            newname = interval+"."+str(index+1)
            logger.debug("moving %s => %s", dirname, newname)
            context.rename(dirname, newname)

def clone_intervals(context, source_interval, dest_intervals):
    if not dest_intervals:
        return

    logger.info("creating clones of %s to %s",
                source_interval,
                ", ".join(dest_intervals))

    processes = []
    srcname = interval_dirname(source_interval, 0)
    for dest_interval in dest_intervals:
        dirname = interval_dirname(dest_interval, 0)
        processes.append(
            (context.cp_al_async(srcname, dirname), dirname))

    while processes:
        remove_idx = None
        for i, (process, dirname) in enumerate(processes):
            try:
                returncode = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                continue
            else:
                if returncode != 0:
                    logger.warn("failed to clone backup to %s",
                                dirname)
                remove_idx = i

        if remove_idx is not None:
            _, dirname = processes.pop(remove_idx)
            logger.info("clone to %s is finished", dirname)
