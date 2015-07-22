import contextlib
import logging
import os
import sys
import time

logger = logging.getLogger(__name__)

class DirectoryContext:
    """
    Execute commands in a fixed directory.

    When the context is entered, the current directory is changed to
    the given directory *chto*. Upon leaving the context, the
    current directory is restored to the one which was set when the
    context was created.
    """

    def __init__(self, ctx, chto):
        self.ctx = ctx
        self.chto = chto

    def __enter__(self):
        self.prevcwd = os.getcwd()
        self.ctx.chdir(self.chto)
        return self

    def __exit__(self, *args):
        self.ctx.chdir(self.prevcwd)

    def __str__(self):
        return "chdir({!r})".format(self.chto)

class MountlikeContext:
    def __init__(self, *, umount_if_mounted=True, force_umount=False, **kwargs):
        super().__init__(**kwargs)
        self.umount_if_mounted = umount_if_mounted
        self.force_umount = force_umount
        self._mounted = False

    def __exit__(self, *exc_info):
        if (self._mounted and self.umount_if_mounted) or self.force_umount:
            self._umount(*exc_info)

class MountContext(MountlikeContext):
    """
    Mount a given device node (*devnode*) at a given *mountpoint* with
    a given set of *options*.

    When entering the context, the given *devnode* is mounted at
    *mountpoint* using the given *options*. *options* must be either
    :data:`None` (for no options) or a string which will be passed to
    the ``-o`` option of the ``mount`` command.

    Upon leaving the context, the mount point is cleared using
    ``umount``.
    """

    def __init__(self, ctx, devnode, mountpoint,
                 options=None,
                 **kwargs):
        super().__init__(**kwargs)
        self.ctx = ctx
        self.devnode = devnode
        self.mountpoint = mountpoint
        self.options = options

    def __enter__(self):
        if os.path.ismount(self.mountpoint):
            return self
        args = [self.devnode, self.mountpoint]
        if self.options is not None:
            args.insert(0, "-o")
            args.insert(1, self.options)
        self.ctx.check_call(["mount"] + args)
        self._mounted = True
        return self

    def _umount(self, *args):
        self.ctx.check_call(["umount", self.mountpoint])

    def __str__(self):
        return "mount({} at {!r})".format(self.devnode, self.mountpoint)

class CryptoContext(MountlikeContext):
    """
    Opens a cryptsetup luks device for usage.

    When entering the context, the luks device at *devnode* is opened
    as with the name *nodename* and an optional *keyfile*. *keyfile*
    must be the path to a file containing (only! no newlines!) the
    passphrase which is to be used to open the crypto container. If
    *keyfile* is :data:`None`, ``cryptsetup`` will prompt for a
    password on stdin.

    Upon leaving the context, the crypto container is closed again.
    """

    def __init__(self, ctx, devnode, nodename, keyfile=None, **kwargs):
        super().__init__(**kwargs)
        self.ctx = ctx
        self.devnode = devnode
        self.nodename = nodename
        self.keyfile = keyfile
        self.mapped_device = os.path.join("/dev", "mapper", nodename)
        self._opened = False

    def __enter__(self):
        if self.ctx.isdev(self.mapped_device):
            return self
        args = ["luksOpen", self.devnode, self.nodename]
        if self.keyfile is not None:
            args.insert(0, "-d")
            args.insert(1, self.keyfile)
        self.ctx.check_call(["cryptsetup"] + args)
        self._mounted = True
        return self

    def _umount(self, *args):
        self.ctx.check_call(["cryptsetup", "luksClose", self.nodename])

    def __str__(self):
        return "luks({} as {!r})".format(self.devnode, self.nodename)

class SuspendContext:
    """
    Suspend a given hard drive when leaving the context.

    When entering the context, nothing happens.

    Upon leaving the context without error, the hard drive
    at *devnode* is suspended using ``hdparm -Y``.
    """

    def __init__(self, ctx, devnode):
        self.ctx = ctx
        self.devnode = devnode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            # only send to sleep if no exception was raised
            self.ctx.check_call(["hdparm", "-Y", self.devnode])

    def __str__(self):
        return "suspend({} on success)".format(self.devnode)

class WaitContext:
    """
    Wait for a device node to appear.

    When entering the context, it starts polling for the device node
    *devnode* for at most *timeout* seconds. If the device does not
    show up, a FileNotFoundError is raised. The context will poll
    :attr:`STEP_COUNT` times and sleep inbetween. If a
    *waiting_callback* is specified, it is called with the time which
    has passed since the start of the waiting period at each step
    (even at the first step with a time of zero).

    Upon leaving the context, nothing happens.
    """

    STEP_COUNT = 5

    def __init__(self, ctx, devnode, timeout=30, waiting_callback=None):
        self.ctx = ctx
        self.devnode = devnode
        self.timeout = timeout
        self.step = timeout/self.STEP_COUNT
        self.waiting_callback = waiting_callback

    def _waiting(self, since):
        if self.waiting_callback:
            self.waiting_callback(since, self.timeout-since)

    def __enter__(self):
        if not self.ctx.isdev(self.devnode):
            self._waiting(0)
            for i in range(1, self.STEP_COUNT+1):
                time.sleep(self.step)
                if not self.ctx.isdev(self.devnode):
                    self._waiting((i+1)*self.step)
                else:
                    break
            else:
                raise FileNotFoundError("device didn't show up in time")
        return self

    def __exit__(self, *args):
        pass

    def __str__(self):
        return "wait-for({})".format(self.devnode)

def create_target_device_context(ctx,
                                 umount_if_mounted=True,
                                 force_umount=False,
                                 waiting_callback=None):
    """
    Return an iterable of context manager, which can be added e.g. to a
    :class:`contextlib.ExitStack`. When all contexts are entered successfully,
    the current working directory is the root directory of the backup device.
    """
    if ctx.base.dest_mount:
        dev = ctx.base.dest_device

        yield WaitContext(ctx, dev, waiting_callback=waiting_callback)

        if ctx.base.dest_device_suspend and umount_if_mounted:
            yield SuspendContext(ctx, dev)

        if ctx.base.dest_cryptsetup:
            crypto = CryptoContext(
                ctx, dev,
                ctx.base.dest_cryptsetup_name,
                keyfile=ctx.base.dest_cryptsetup_keyfile,
                force_umount=force_umount,
                umount_if_mounted=umount_if_mounted
            )
            yield crypto
            dev = crypto.mapped_device

        yield MountContext(
            ctx, dev,
            ctx.base.dest_root,
            ctx.base.dest_mount_options,
            force_umount=force_umount,
            umount_if_mounted=umount_if_mounted)

    yield DirectoryContext(ctx, ctx.base.dest_root)

class DeviceContext(contextlib.ExitStack):
    def __init__(self, ctx, args):
        super().__init__()
        self.ctx = ctx
        self.args = args

    def __enter__(self):
        result = super().__enter__()
        for part in create_target_device_context(
                self.ctx,
                umount_if_mounted=self.args.umount,
                force_umount=self.args.force_umount,
                waiting_callback=self.ctx.device_missing):
            logger.debug("%s", part)
            result.enter_context(part)
        return result
