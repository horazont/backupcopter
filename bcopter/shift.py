"""
In this file, the shifting and management of backup "intervals" is
handled. Remember that backupcopter itself does not know about
time. It only knows which backup intervals it is supposed to do at one
specific call.
"""
import logging
import os

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
    Shift directories belonging to one interval upwards. If would be
    too many directories after shifting, the directory with the
    highest number is deleted *beforehands*.
    """
    indicies = interval_indicies(interval)

    indicies.sort(reverse=True)
    my_depth = context.base.intervals_shiftdepth[interval]
    for index, dirname in indicies:
        if index >= my_depth-1:
            logger.info("removing surplus folder: %s", dirname)
            context.deltree(dirname)
        else:
            newname = interval+"."+str(index+1)
            logger.info("moving %s => %s", dirname, newname)
            context.rename(dirname, newname)

def do_interval_shift(context, upper_interval, lower_interval):
    """
    Shift up the directory with the suffix corresponding to the
    shift-depth of the *lower_interval* to the *upper_interval*.

    If that directory does not exist, a warning is logged and nothing
    further happens.
    """
    lower_dirname = interval_dirname(
        lower_interval,
        context.base.intervals_shiftdepth[lower_interval]-1)

    upper_dirname = interval_dirname(upper_interval, 0)

    try:
        logging.info("shifting up %s to %s", lower_dirname, upper_dirname)
        context.rename(lower_dirname, upper_dirname)
    except FileNotFoundError:
        logging.warn("cannot shift %s -- it does not exist!", lower_dirname)
