import logging
import sys
import os
import time

logger = logging.getLogger(__name__)

class ChainedContexts:
    """
    Chain several contexts together, managing rollback on error for
    each one, even if the error happens while setting up nested
    contexts.
    """
    def __init__(self, *contexts):
        self._contexts = []
        for name, ctx in contexts:
            if name.startswith("_"):
                raise ValueError("Invalid context name: {}".format(name))
            setattr(self, name, ctx)
            self._contexts.append(ctx)

    def _rollback(self, exits, *args):
        propagate = True
        for i, method in reversed(list(enumerate(exits))):
            try:
                if not method(*args):
                    exc_type = None
                    exc_value = None
                    traceback = None
                    propagate = False
            except Exception as err:
                self._rollback(exits[:i], *sys.exc_info())
                raise
        return propagate

    def __enter__(self):
        self._exit_methods = [context.__exit__ for context in self._contexts]

        for i, context in enumerate(self._contexts):
            try:
                context.__enter__()
            except Exception as err:
                self._rollback(self._exit_methods[:i], *sys.exc_info())
                raise
        return self

    def __exit__(self, *args):
        self._rollback(self._exit_methods, *args)

    def __str__(self):
        return "stack({})".format("\n".join(map(str, self._contexts)))

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

class MountContext:
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

    def __init__(self, ctx, devnode, mountpoint, options=None):
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
        return self

    def __exit__(self, *args):
        self.ctx.check_call(["umount", self.mountpoint])

    def __str__(self):
        return "mount({} at {!r})".format(self.devnode, self.mountpoint)

class CryptoContext:
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

    def __init__(self, ctx, devnode, nodename, keyfile=None):
        self.ctx = ctx
        self.devnode = devnode
        self.nodename = nodename
        self.keyfile = keyfile
        self.mapped_device = os.path.join("/dev", "mapper", nodename)

    def __enter__(self):
        if self.ctx.isdev(self.mapped_device):
            return self
        args = ["luksOpen", self.devnode, self.nodename]
        if self.keyfile is not None:
            args.insert(0, "-d")
            args.insert(1, self.keyfile)
        self.ctx.check_call(["cryptsetup"] + args)
        return self

    def __exit__(self, *args):
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

def create_target_device_context(ctx, waiting_callback=None):
    """
    Create and return a usable context using the configuration options
    found in *ctx*.
    """
    contexts = []

    if ctx.base.dest_mount:
        dev = ctx.base.dest_device

        contexts.append(("waitfor", WaitContext(ctx, dev, waiting_callback=waiting_callback)))

        if ctx.base.dest_device_suspend:
            contexts.append(("suspend", SuspendContext(ctx, dev)))

        if ctx.base.dest_cryptsetup:
            crypto = CryptoContext(ctx, dev, ctx.base.dest_cryptsetup_name, keyfile=ctx.base.dest_cryptsetup_keyfile)
            contexts.append(("crypto", crypto))
            dev = crypto.mapped_device

        contexts.append(("mount", MountContext(ctx, dev, ctx.base.dest_root, ctx.base.dest_mount_options)))

    contexts.append(("cd", DirectoryContext(ctx, ctx.base.dest_root)))
    return ChainedContexts(*contexts)
