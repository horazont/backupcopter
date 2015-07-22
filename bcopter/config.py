import configparser
import sys
import os
import stat
import textwrap

class MissingOptionError(Exception):
    def __init__(self, instance, propobj, inferrenceerr=None):
        super().__init__(instance, propobj)
        self.instance = instance
        self.propobj = propobj
        self.inferrenceerr = inferrenceerr

    def __str__(self):
        return "{!s} misses option {}{inferrencetext}".format(
            self.instance,
            self.propobj.beautiful_name,
            inferrencetext="" if self.inferrenceerr is None else " ({})".format(self.inferrenceerr))

class ValidationError(Exception):
    def __init__(self, instance, propobj, origexc):
        super().__init__(instance, propobj, origexc)
        self.instance = instance
        self.propobj = propobj
        self.origexc = origexc

    def __str__(self):
        return "{!s}: {} is invalid: {!s}: {!s}".format(
            self.instance,
            self.propobj.beautiful_name,
            type(self.origexc).__name__,
            self.origexc
        )

class UnknownOptionError(Exception):
    def __init__(self, instance, name):
        super().__init__(instance, name)
        self.instance = instance
        self.name = name

    def __str__(self):
        return "{!s}: has unknown option: {}".format(self.instance, self.name)

class ConfigMeta(type):
    @staticmethod
    def validate(self, raise_on_error=True):
        if not raise_on_error:
            errors = []
        for name, obj in sorted(self.__properties__.items()):
            result = obj._validate(self)
            if result is not None:
                if raise_on_error:
                    raise result
                else:
                    errors.append(result)
        return errors if not raise_on_error else None

    @staticmethod
    def dump(self, file):
        for name, obj in sorted(self.__properties__.items()):
            if hasattr(self, obj._varname):
                value = getattr(self, obj._varname)
                if value != obj._default:
                    print("{}={}".format(obj._beautiful_name, value, file=file), file=file)

    def __new__(mcls, name, bases, dct):
        dct["parent_config"] = None
        properties = {}
        for key, value in list(dct.items()):
            if isinstance(value, config_property):
                varname, default = value._finalize(key)
                if not value._required:
                    dct[varname] = default
                properties[key] = value

        dct["dump_config"] = mcls.dump
        dct["validate_config"] = mcls.validate

        base_properties = {}
        for base in bases:
            if hasattr(base, "__properties__"):
                base_properties.update(base.__properties__)
        base_properties.update(properties)
        dct["__properties__"] = base_properties
        dct["__local_properties__"] = properties

        inst = type.__new__(mcls, name, bases, dct)
        return inst

class config_property:
    def __init__(self, default=None, docstring=None, inherit=True,
                 validator=None, required=False, type=None,
                 missingfunc=None):
        self._finalized = False
        self._default = default
        self._missingfunc = missingfunc
        self._varname = None
        self.name = None
        self._docstring = docstring
        self._beautiful_name = None
        self._inherit = inherit
        self._validator = validator
        self._required = required
        self._type = type

    def _finalize(self, propname):
        assert not self._finalized
        self._varname = "_" + propname
        self.name = propname
        self._beautiful_name = propname.replace("_", ".")
        return self._varname, self._default

    def _validate(self, instance):
        if self._required and not hasattr(instance, self._varname):
            if self._missingfunc:
                try:
                    self.__set__(instance, self._missingfunc(instance))
                except Exception as err:
                    return MissingOptionError(instance, self, err)
            else:
                return MissingOptionError(instance, self)
        value = self.__get__(instance, type(instance))
        if self._validator is not None:
            try:
                self._validator(instance, value, self)
            except Exception as err:
                return ValidationError(instance, self, err)

    def __get__(self, instance, owner):
        if instance is not None:
            result = self._default
            if self._varname not in instance.__dict__:
                if self._inherit:
                    parent = instance.parent_config
                    if parent is not None and hasattr(parent, self.name):
                        result = getattr(parent, self.name)
            else:
                result = getattr(instance, self._varname)
            return result
        else:
            return self

    def __set__(self, instance, value):
        if self._type is not None:
            value = self._type(value)
        # print("setting {}.{} = {}".format(instance, self.name, value))
        setattr(instance, self._varname, value)

    def __delete__(self, instance):
        delattr(instance, self._varname)

    @property
    def beautiful_name(self):
        return self._beautiful_name

def file_access(mode):
    def file_access(instance, value, propobj):
        if value is None:
            return
        try:
            if not os.access(value, mode):
                return PermissionError(value)
        except OSError as err:
            return err
    return file_access

def integer(value):
    return int(value)

def boolean(value):
    value = value.strip().lower()
    if value in {"true", "1"}:
        return True
    elif value in {"false", "0"}:
        return False
    else:
        raise ValueError("not a valid boolean: {}".format(value))

def strlist(value):
    import ast
    if isinstance(value, str):
        value = ast.literal_eval(value)
        if isinstance(value, str) or isinstance(value, dict) or isinstance(value, set):
            raise ValueError("not a valid list: {!r}".format(value))
        return strlist(value)
    else:
        return list(map(str, value))

def mapping(fromtype, totype):
    def mapping(value):
        import ast
        if isinstance(value, str):
            value = ast.literal_eval(value)
            if isinstance(value, str):
                raise ValueError("not a valid mapping: {!r}".format(value))
            return mapping(value)
        else:
            return {fromtype(k): totype(v) for k, v in dict(value).items()}
    return mapping

def host_and_path_from_section_name(instance):
    name = instance.name
    try:
        host, path = name.split(":", 1)
    except ValueError:
        raise ValueError('Could not deduce host and path from target name "{}"'.format(name))
    return host, path

def source_from_section_name(instance):
    host, path = host_and_path_from_section_name(instance)
    return os.path.normpath(path) + "/"

def dest_from_section_name(instance):
    host, path = host_and_path_from_section_name(instance)
    if path and path[0] == "/":
        path = path[1:]

    return os.path.normpath(os.path.join(host, path)) + "/"

def absolute_path(instance, value, propobj):
    if not os.path.isabs(value):
        raise ValueError("Source path must be absolute (got \"{}\")".format(value))

def source_path(instance, value, propobj):
    try:
        host, path = value.split(":", 1)
    except ValueError:
        absolute_path(instance, value, propobj)
    else:
        if "/" in host:
            absolute_path(instance, value, propobj)
        raise ValueError("Do not specify user/protocol in source directly. Use source.prefix for that!")

def dest_path(instance, value, propobj):
    if os.path.isabs(value):
        raise ValueError("Destination path must be relative (got \"{}\"). I'll put it in the correct context for you.".format(value))

def parallel_mode(value):
    value = value.strip().lower()
    try:
        return int(value)
    except ValueError as err:
        if value == "false":
            return False
        else:
            raise err

def require_local(instance, value, propobj):
    if value and not instance.local:
        raise ValueError("This requires a local host")

def require_remote(instance, value, propobj):
    if value and instance.local:
        raise ValueError("This requires a remote host")

def host_from_section_name(instance):
    host, _ = host_and_path_from_section_name(instance)
    return host

def mk_absolute_path(path):
    return os.path.abspath(path)

class CommonConfig(metaclass=ConfigMeta):
    """
    These are common options used in multiple places in
    backupcopter. None of these are required, but they offer some
    customization which might be desired.
    """

    group = config_property()
    ssh_args = config_property(
        type=strlist,
        docstring="""Additional arguments to pass to ssh. Syntax: ["-A", "-Y"]
    would enable agent and insecure X11 forwarding. Not recommended.""")
    #parallel = config_property(type=parallel_mode, default=False)
    ssh_port = config_property(
        type=integer,
        docstring="""An integer tcp port number to pass to
    ssh. Omitting leaves it to ssh's defaults (which may include
    reading .ssh/config)""")
    #ssh_user = config_property(
    #    validator=require_remote)
    ssh_identity = config_property(
        type=mk_absolute_path,
        validator=file_access(os.R_OK),
        docstring="""Path to the private key to use to connect using
    ssh. If the key requires a passphrase, it will be prompted for on
    the terminal.""")

    trickle_upstream_limit = config_property(
        type=integer,
        docstring="""An integer number which gives the maximum
        approximate upstream for ssh, if trickle.enable is set to
        True, in kilobytes per second.""")
    trickle_downstream_limit = config_property(
        type=integer,
        docstring="""An integer number which gives the maximum
        approximate downstream for ssh, if trickle.enable is set to
        True, in kilobytes per second.""")
    trickle_enable = config_property(
        type=boolean,
        docstring="""Whether to enable trickle (requires trickle.cmd
        to be set).""")
    trickle_standalone = config_property(
        type=boolean,
        default=True,
        docstring="""Whether to use trickles standalone mode (default
        is on).""")

    ionice_enable = config_property(
        type=boolean,
        docstring="""Whether to enable ionice limits for rsync."""
        )
    ionice_class = config_property(
        type=integer,
        docstring="""The ionice class (see ionice manpage for further details).""")
    ionice_level = config_property(
        type=integer,
        docstring="""The ionice level (see ionice manpage for further details).""")

    source_btrfs = config_property(
        type=boolean,
        default=False,
        validator=require_local,
        docstring="""Whether the backup source resides on a
        btrfs. This is only allowed for local hosts.""")


class HostConfig(CommonConfig, metaclass=ConfigMeta):
    """
    These are additional per-host options, which can be set in
    addition to the Common Options listed above.

    It is recommended to outsource e.g. per host ssh and rate limiting
    configuration to host sections and reference the hosts from the
    backup targets.
    """
    local = config_property(
        required=True,
        type=boolean,
        docstring="""Whether this is a local host or a remote
    host. For non-local hosts, btrfs snapshots cannot be used and it
    is dangerous to mislabel the localness of hosts if btrfs is used!""")
    source_prefix = config_property(
        validator=require_remote,
        default="",
        docstring="""Prefix to add to the source path of a backup
    target. Usually, you'll want to write something like user@remote:
    (including the trailing colon!) here for remote hosts.""")

def load_hosts(value):
    parser = configparser.ConfigParser()
    with open(value, "r") as config_file:
        parser.read_file(config_file)
    hosts = []
    for section in parser.sections():
        host = HostConfig()
        host.name = section
        option_dict = dict(parser.items(section))
        for name, propobj in host.__properties__.items():
            try:
                value = option_dict[propobj.beautiful_name]
                del option_dict[propobj.beautiful_name]
            except KeyError:
                continue
            setattr(host, name, value)

        if option_dict:
            key = next(iter(option_dict.keys()))
            raise UnknownOptionError(host, key)

        hosts.append(host)
    return hosts

def validate_hosts(instance, value, propobj):
    for host in value:
        host.parent_config = instance
        host.validate_config(raise_on_error=True)

def raise_if_cryptsetup(instance):
    if instance.dest_cryptsetup:
        raise ValueError("required when using cryptsetup")

def validate_mount(instance, value, propobj):
    if value and not instance.dest_device:
        raise ValueError("mount must be set to False if no device is given")

def validate_intervals(instance, value, propobj):
    if not value:
        raise ValueError("More than zero intervals are required")

def validate_intervals_shiftdepth(instance, value, propobj):
    interval_set = set(instance.intervals)
    for k in value.keys():
        if not k in interval_set:
            raise ValueError("Undefined interval: {}".format(k))

def need_device(instance, value, propobj):
    if not instance.dest_device:
        raise ValueError("requires device")

def false_if_no_device(instance, value, propobj):
    if not instance.dest_device:
        propobj.__set__(instance, "False")

def raise_if_btrfs_volumes(instance):
    if instance.source_btrfs_volumes:
        raise ValueError("required if btrfs volumes are set")

class BaseConfig(CommonConfig, metaclass=ConfigMeta):
    """
    This is the global configuration for backupcopter. Some of these
    options are required and it is highly recommended that you read
    through all options' documentation before using backupcopter to
    avoid unwanted sideeffects.

    The options listed here are supported in addition to the Common
    Options listed above.
    """

    hosts = config_property(
        default={},
        type=load_hosts,
        validator=validate_hosts,
        docstring="""Specify another configuration file here which
    contains host information. Hosts can be used to group together
    options for multiple targets."""
        )
    ssh_cmd = config_property(
        validator=file_access(os.X_OK),
        docstring="""Specify the ssh command. This is required if
        you're going to do remote backups."""
        )
    trickle_cmd = config_property(
        validator=file_access(os.X_OK),
        docstring="""The path to the trickle application. It can be used to
    rate-limit ssh inside rsync."""
        )
    ionice_cmd = config_property(
        validator=file_access(os.X_OK),
        docstring="""The path to the ionice application. It can be
    used to rate-limit the general I/O rsync uses."""
        )
    rm_cmd = config_property(
        validator=file_access(os.X_OK),
        docstring="""Path to the rm binary. If omitted, we'll use our
    own rm-rf-implementation."""
        )
    cp_cmd = config_property(
        validator=file_access(os.X_OK),
        docstring="""Path to a cp implementation which supports
    archive and hardlink modes (GNU cp does). If omitted, rollback
    won't work properly and backup won't work at all if rsync does not
    support --link-dest."""
        )
    rsync_cmd = config_property(
        required=True,
        validator=file_access(os.X_OK),
        docstring="""Path to the rsync binary."""
        )
    rsync_linkdest = config_property(
        type=boolean,
        default=True,
        docstring="""Set this to False if your rsync does not support
    --link-dest. See the documentation of cp.cmd for possible implications!""")
    rsync_onefs = config_property(
        type=boolean,
        default=False,
        docstring="""Set this to True if you don't want rsync to cross
    filesystem boundaries.""")
    rsync_args = config_property(
        type=strlist,
        docstring="""Can be a list of string arguments which are also
    passed to rsync. Use ["foo", "bar"] to pass the arguments foo and
    bar to rsync."""
        )
    rsync_args_remote = config_property(
        type=strlist,
        docstring="""Can be a list of string arguments which are also
        passed to rsync, but only if the target is on a remote
        host. They are appended to the already constructed argument
        list. Use ["--bwlimit", "500"] to limit the bandwidth to 500
        kByte/s.""")

    usertowarn = config_property(
        required=False,
        default=None,
        docstring="""The name of the usually logged on user on the
        machine. If the backup device is not always available (and you
        set dest.device), this user will receive an X11 notification
        and has 30 seconds of time to make the device available
        (e.g. turn on and plug in an external hard drive.""")

    dest_root = config_property(
        required=True,
        docstring="""Path to the directory where the backups will be
        kept.""")
    # dest_nocreate = config_property(type=boolean)

    dest_cryptsetup = config_property(
        type=boolean,
        docstring="""Set this to true if your backup device is
        encrypted using LUKS/cryptsetup.""")
    dest_cryptsetup_name = config_property(
        required=True,
        missingfunc=raise_if_cryptsetup,
        docstring="""The cryptsetup/mapper name to use for the
        device. This can generally be a freeform name, I suggest
        omitting spaces and other special characters.""")
    dest_cryptsetup_keyfile = config_property(
        validator=file_access(os.R_OK),
        docstring="""If set, it must be a readable file which contains
        the passphrase of the encrypted device. If you do not specify
        this and use cryptsetup, you'll have to type the password on
        the shell backupcopter runs on.""")
    dest_mount = config_property(
        type=boolean,
        default=True,
        validator=validate_mount,
        docstring="""If set to false, it is assumed that no mounting
        has to be done for the backup to start. This conflicts with
        dest.cryptsetup and dest.device.""")
    dest_mount_options = config_property(
        default=None,
        docstring="""Options passed to mount via -o upon mounting the
        backup target device."""
        )
    dest_device = config_property(
        required=True,
        missingfunc=raise_if_cryptsetup,
        docstring="""Path to the block device to use as a
        destination. Required of dest.nomount is not set or if
        dest.cryptsetup is enabled. Make sure it's persistent and you
        don't accidentially mount the wrong device (i.e. use
        /dev/disk/by-uuid).""")
    dest_device_suspend = config_property(
        type=boolean,
        validator=false_if_no_device,
        docstring="""Send the hard disk to sleep using hdparm -Y after
        the backup has finished. This requires dest.device.""")

    source_btrfs_volumes = config_property(
        type=strlist,
        docstring="""If the local(!) source is using btrfs, you can
        specify a list of subvolume paths here, which will be
        automatically snapshotted before the backup. The backup will
        then use the snapshots as a source, which are deleted after
        the backup has finished. This ensures atomic backups to a
        certain extent. This does not work with remote sources and
        will be ignored for these. Specify paths with a ["/",
        "/home"]-like syntax (this would add the paths / and /home as
        known subvolumes to be snapshotted). EXPERIMENTAL""")
    source_btrfs_snapshotdir = config_property(
        required=True,
        missingfunc=raise_if_btrfs_volumes,
        docstring="""Path where the subvolume snapshots can be
        temporarily mounted. This must be an empty directory to which
        backupcopter can mount snapshots.""")

    intervals = config_property(
        required=True,
        type=strlist,
        validator=validate_intervals,
        docstring="""A list of backup intervals. These are names you
        can choose, which must be valid directory names and should not
        contain spaces. Specify them like this: ["daily", "weekly"].
        See the `Backup model` section for more details on intervals.
        """)
    intervals_shiftdepth = config_property(
        required=True,
        type=mapping(str, int),
        validator=validate_intervals_shiftdepth,
        docstring="""A mapping defining how many rounds a backup will
        rotate before it's either moved to the next interval level or
        deleted. Specify like this: {"daily": 7, "weekly": 4}. This
        would allow for seven daily backups. See the `Backup model`
        section for more details on intervals."""
        )
    intervals_run_only_lowest = config_property(
        type=boolean,
        default=True,
        docstring="""If set to true, no backups will be run except if
        the lowest interval is specified among the backup intervals.
        Otherwise, only shifting and cloning takes place. See the
        `Backup model` section for more details on intervals.""")


    def __str__(self):
        return "base config"

class BackupTarget(HostConfig, metaclass=ConfigMeta):
    """
    Specify configuration options for backup targets. Bascially, you
    can name backup targets however you want, but I recommend the
    following naming scheme, since it allows for an astonishing
    brevity:

        [hostname:/absolute/path]

    where hostname is a name of your choice (which should be a valid
    directory name) for the host you're backing up and /absolute/path
    is the absolute path to the source directory on that host.

    backupcopter will automatically deduce the hostname and the path
    if they're not set explicitly in the backup target if you use this
    syntax, so that you can omit source, dest and host.

    The targets of course also support overriding all options allowed
    in Hosts and the Common Options listed above.
    """

    name = None
    local = config_property(inherit=True)
    source = config_property(
        required=True,
        missingfunc=source_from_section_name,
        validator=source_path,
        docstring="""The absolute source path from which to backup. If
    you're doing remote backups, use source.prefix to specify the
    hostname (read the docs of source.prefix for more information).""")
    dest = config_property(
        required=True,
        missingfunc=dest_from_section_name,
        validator=dest_path,
        docstring="""The relative path at which to store the
    backup. Usually, you'll want to use something like
    host/path/on/host.""")
    host = config_property(
        required=True,
        missingfunc=host_from_section_name,
        docstring="""A name from the hosts config file (see [base]
    hosts). If set, the options given for that host will be inherited
    for this backup.""")

    def __str__(self):
        return "target \"{}\"".format(self.name)

class Config:
    def __init__(self):
        super().__init__()
        self.reset()

    def _load_object(self, obj, options):
        option_dict = dict(options)
        for name, propobj in obj.__properties__.items():
            try:
                value = option_dict[propobj.beautiful_name]
                del option_dict[propobj.beautiful_name]
            except KeyError:
                continue
            try:
                setattr(obj, name, value)
            except (ValueError, TypeError) as err:
                self._collected_errors.append(ValidationError(obj, propobj, err))

        for key in option_dict.keys():
            self._collected_errors.append(UnknownOptionError(obj, key))

    def _load_base(self, options):
        self._load_object(self.base, options)
        self.hosts = {host.name: host for host in self.base.hosts}

    def _load_target(self, name, options):
        target = BackupTarget()
        target.name = name
        target.parent_config = self.base

        self._load_object(target, options)
        if target.host is None:
            target.host = host_from_section_name(target)
        if target.host is not None:
            try:
                host = self.hosts[target.host]
            except KeyError:
                self._collected_errors.append(KeyError("Unknown host: {} (did you forget specifiying hosts in [base]?)".format(host)))
            else:
                target.parent_config = host
                assert host.local == target.local
        self.target_map[name] = target
        self.targets.append(target)

    def reset(self):
        self.base = BaseConfig()
        self.targets = []
        self.target_map = {}
        self.hosts = dict()
        self._collected_errors = []

    def load(self, filelike, raise_on_error=True):
        parser = configparser.ConfigParser()
        if isinstance(filelike, str):
            parser.read([filelike])
        else:
            parser.read_file(filelike)

        self._load_base(parser.items("base"))
        for section in parser.sections():
            if section != "base":
                self._load_target(section, parser.items(section))

        try:
            errors = self.validate(raise_on_error=raise_on_error)
        except:
            self.reset()
            raise
        return errors

    def validate(self, raise_on_error=True):
        if not raise_on_error:
            errors = self._collected_errors
            self._collected_errors = []
            errors.extend(self.base.validate_config(raise_on_error=False))
            for target in self.targets:
                errors.extend(target.validate_config(raise_on_error=False))
            return errors
        else:
            if self._collected_errors:
                err = self._collected_errors.pop(0)
                self._collected_errors = []
                raise err
            self.base.validate_config(raise_on_error=True)
            for target in self.targets:
                target.validate_config(raise_on_error=True)

    def dump(self, file=sys.stdout):
        print("[base]", file=file)
        self.base.dump_config(file)
        for target in self.targets:
            print("", file=file)
            print("[{}]".format(target.name, file=file))
            target.dump_config(file)

def print_options(cls, wrapper):
    for _, propobj in sorted(cls.__local_properties__.items()):
        if propobj._docstring is None:
            continue
        print("{}".format(propobj.beautiful_name))
        print(wrapper.fill(" ".join(propobj._docstring.split())))
        print()

def fillprint(text):
    print(textwrap.fill(" ".join(text.split())))

def print_config_options():
    wrapper = textwrap.TextWrapper()
    wrapper.subsequent_indent = "    "
    wrapper.initial_indent = "    "

    print("""backupcopter -- flexible rsync wrapper""")
    print()
    print()
    print("Configuration File Syntax")
    print("#########################")
    print("   A brief introduction")
    print()
    fillprint("""The configuration file syntax used by backupcopter is
    the one of the python configparser module, which is also known as
    ini file syntax. Options are grouped into sections. Sections have
    headers, which is just a string enclosed in square brackets,
    e.g.:""")
    print()
    print("    [some section name]")
    print()
    fillprint("""The main configuration has one predefined section,
    which is the [base] section. In that section, global configuration
    options such as paths to certain tools are set. Scroll down to
    Global Options for reading more on the options allowed in the
    [base] section.""")
    print()
    fillprint("""The other sections are the backup target sections,
    which specify which directories on which hosts are backed up. A
    backup target section can in principle have any name you imagine,
    but it is recommended to use a naming scheme like:""")
    print()
    print("    [hostname:/path/to/data]")
    print()
    fillprint("""Here, hostname is a short name you assign to the host
    you want to backup. It is an opaque token -- it does not need to
    be an actual FQDN or something like this, but it should be a valid
    directory name and obviously cannot contain a colon or square
    brackets. You don't have to use that scheme, but it makes things
    easier.""")
    print()
    fillprint("""If you use that specific naming scheme, you don't
    have to specify the paths and host names again inside the
    section. backupcopter will infer these from the section name if
    required (i.e. if you have omitted the affected options.""")
    print()
    fillprint("""The options allowed in backup target sections are
    described below in the Backup Options section.""")
    print()
    fillprint("""There is a second configuration file in use, which is
    in principle optional, but required if you use the naming scheme
    above. That configuration file controls host-specific settings,
    which are referred to from each backup target. This is quite
    useful if you are backing up multiple hosts.""")
    print()
    fillprint("""That configuration file contains one section for each
    host, the section name is just the hostname. The allowed options
    are described below in the section Host Options.""")

    print()
    print()
    print("Backup model")
    print("############")
    print()
    fillprint("""backupcopter works in the following way. You specify a
    configuration and a set of intervals. Intervals are an abstraction
    of the time intervals in which you make incremental backups.""")
    print()
    fillprint("""Each interval gains its own set of directories, named
    and numbered by the interval name and the count of backups existing
    with that interval. Upon creating a backup, the existing directories
    of the affected interval are shifted up by one number. If too many
    directories exist (i.e. more than set in the configuration as the
    `shiftdepth` of that interval), the surplus directories are
    deleted.""")
    print()
    fillprint("""If multiple intervals are to be backed up at once,
    backupcopter will only make one actual backup and create a
    hardlinked copy of that backup in the other intervals, to save I/O
    and space and to create consistent backups.""")

    print()
    print()
    print("Configuration Option Reference")
    print("##############################")
    print()
    print("Common Options")
    print("==============")
    print(CommonConfig.__doc__)
    print_options(CommonConfig, wrapper)
    print()
    print("Global Options")
    print("==============")
    print(BaseConfig.__doc__)
    print_options(BaseConfig, wrapper)
    print()
    print("Backup Options")
    print("==============")
    print(BackupTarget.__doc__)
    print_options(BackupTarget, wrapper)
    print()
    print("Host Options")
    print("============")
    print(HostConfig.__doc__)
    print_options(HostConfig, wrapper)
