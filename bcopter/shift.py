import logging
import os

logger = logging.getLogger(__name__)

def interval_dirname(interval, index):
    return interval + "." + str(index)

def interval_indicies(interval):
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
    lower_dirname = interval_dirname(
        lower_interval,
        context.base.intervals_shiftdepth[lower_interval]-1)

    upper_dirname = interval_dirname(upper_interval, 0)

    try:
        logging.info("shifting up %s to %s", lower_dirname, upper_dirname)
        context.rename(lower_dirname, upper_dirname)
    except FileNotFoundError:
        logging.warn("cannot shift %s -- it does not exist!", lower_dirname)
