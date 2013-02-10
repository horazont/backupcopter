import configparser
import sys
import os
import stat

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
            result = self._validator(instance, value, self)
            if result is not None:
                return ValidationError(instance, self, result)

    def __get__(self, instance, owner):
        if instance is not None:
            result = self._default
            if not hasattr(instance, self._varname):
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
        return ValueError("Source path must be absolute (got \"{}\")".format(value))

def source_path(instance, value, propobj):
    try:
        host, path = value.split(":", 1)
    except ValueError:
        return absolute_path(instance, value, propobj)
    else:
        if "/" in host:
            return absolute_path(instance, value, propobj)
        return absolute_path(instance, path, propobj)

def dest_path(instance, value, propobj):
    if os.path.isabs(value):
        return ValueError("Destination path must be relative (got \"{}\"). I'll put it in the correct context for you.".format(value))

def parallel_mode(value):
    value = value.strip().lower()
    try:
        return int(value)
    except ValueError as err:
        if value == "false":
            return False
        else:
            raise err

class CommonConfig(metaclass=ConfigMeta):
    ssh_args = config_property(type=strlist)
    ssh_identity = config_property(validator=file_access(os.R_OK))
    trickle_upstream_limit = config_property(type=integer)
    trickle_downstream_limit = config_property(type=integer)
    ionice_class = config_property(type=integer)
    ionice_level = config_property(type=integer)
    source_btrfs = config_property(type=boolean, default=False)
    trickle_enable = config_property(type=boolean)
    trickle_standalone = config_property(type=boolean, default=True)
    ionice_enable = config_property(type=boolean)
    group = config_property()
    #parallel = config_property(type=parallel_mode, default=False)

class BaseConfig(CommonConfig, metaclass=ConfigMeta):
    ssh_cmd = config_property(validator=file_access(os.X_OK))
    trickle_cmd = config_property(validator=file_access(os.X_OK))
    ionice_cmd = config_property(validator=file_access(os.X_OK))
    rm_cmd = config_property(validator=file_access(os.X_OK))
    cp_cmd = config_property(validator=file_access(os.X_OK))
    rsync_cmd = config_property(required=True, validator=file_access(os.X_OK))
    rsync_linkdest = config_property(type=boolean)
    rsync_onefs = config_property(type=boolean)
    rsync_args = config_property(type=strlist)
    dest_root = config_property(required=True)
    dest_nocreate = config_property(type=boolean)
    source_btrfs_volumes = config_property(type=strlist)
    source_btrfs_snapshotdir = config_property()
    intervals = config_property(required=True, type=mapping(str, int))

    def __str__(self):
        return "base config"

class BackupTarget(CommonConfig, metaclass=ConfigMeta):
    name = None
    source = config_property(
        required=True,
        missingfunc=source_from_section_name,
        validator=source_path)
    dest = config_property(
        required=True,
        missingfunc=dest_from_section_name,
        validator=dest_path)

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

    def _load_target(self, name, options):
        target = BackupTarget()
        target.name = name
        target.parent_config = self.base

        self._load_object(target, options)

        self.targets.append(target)

    def reset(self):
        self.base = BaseConfig()
        self.targets = []
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
