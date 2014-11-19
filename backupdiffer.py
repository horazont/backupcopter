#!/usr/bin/python3
import argparse
import logging
import os
import sys

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config-file",
        metavar="CONFIGFILE",
    )
    parser.add_argument(
        "source",
        help="Source interval. Can either be an interval name (e.g. daily) or a "
        "full directory name (e.g. daily.2). Specifying only the interval will "
        "use the newest backup from that interval."
    )
    parser.add_argument(
        "targets",
        metavar="TARGET",
        nargs="+",
        help="Backup targets to compare"
    )

    try:
        args = parser.parse_args()
    except argparse.ArgumentError as err:
        parser.print_help()
        print()
        sys.stdout.flush()
        print(str(err), file=sys.stderr)
        sys.stderr.flush()

    logging.basicConfig(level=logging.INFO,
                        format='{0}:%(levelname)-8s %(message)s'.format(
                            os.path.basename(sys.argv[0])))

    import bcopter
    import bcopter.device_context
    import bcopter.shift

    try:
        args.config_file = open(args.config_file, "r")
    except FileNotFoundError as err:
        parser.print_help()
        print()
        sys.stdout.flush()
        print("failed to open config: {}".format(err))
        sys.stderr.flush()
        sys.exit(1)

    conf = bcopter.Context(False)
    try:
        errors = conf.load(args.config_file, raise_on_error=False)
    finally:
        args.config_file.close()
    if errors:
        print("fatal configuration errors found:")
        for error in errors:
            print(str(error))
        sys.exit(2)

    # deliberately disable device suspending
    conf.base.dest_device_suspend = "False"

    context_stack = bcopter.device_context.create_target_device_context(
        conf, waiting_callback=conf.device_missing)

    try:
        with context_stack:
            if not os.path.isdir(args.source):
                indicies = bcopter.shift.interval_indicies(args.source)
                if not indicies:
                    raise RuntimeError("No such source interval: {}".format(
                        args.source))

                indicies.sort()
                args.source = indicies[0][1]

            source_dir = os.path.abspath(args.source)
            logging.info("Using source directory: %s", source_dir)

            for target in args.targets:
                try:
                    target = conf.target_map[target]
                except KeyError:
                    logging.error("No such target: %s", target)
                    continue

                logging.info("Comparing target: %s", target)
                dest = target.source_prefix + target.source
                src = os.path.join(source_dir, target.dest)
                conf.rsync(target, src, dest, additional_args=["-v", "--progress", "--dry-run"])

    except RuntimeError as err:
        print(str(err), file=sys.stderr)
