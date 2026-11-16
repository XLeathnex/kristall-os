# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, fail-soft sysfs helpers.

Every write goes through `write()`, which returns an errno instead of raising, so a lever that is
locked (EACCES), absent (ENOENT) or rejected by the driver (EINVAL, EIO, ...) is reported, never
fatal. Tests can inject kernel behaviour with KRISTALL_POWER_FAULTS (a JSON file mapping host
paths, without the fixture root, to {"errno": N} or {"readback": "value"})."""
import errno
import json
import os

from . import paths

_faults_cache = None


def _faults():
    global _faults_cache
    fn = os.environ.get("KRISTALL_POWER_FAULTS")
    if not fn:
        return {}
    try:
        mtime = os.stat(fn).st_mtime_ns
    except OSError:
        return {}
    if _faults_cache and _faults_cache[0] == (fn, mtime):
        return _faults_cache[1]
    try:
        with open(fn) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    _faults_cache = ((fn, mtime), data)
    return data


def _unroot(path: str) -> str:
    return path[len(paths.ROOT):] if paths.ROOT and path.startswith(paths.ROOT) else path


def read(path: str, default=None):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace").strip()
    except OSError:
        return default


def read_int(path: str, default=None):
    v = read(path)
    if v is None:
        return default
    try:
        return int(v.split()[0])
    except (ValueError, IndexError):
        return default


def exists(path: str) -> bool:
    return os.path.exists(path)


def listdir(path: str):
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def write(path: str, value) -> int:
    """Write `value`; return 0 on success or the errno."""
    fault = _faults().get(_unroot(path))
    if fault and "errno" in fault:
        return int(fault["errno"])
    if not os.path.exists(path):
        return errno.ENOENT
    try:
        with open(path, "w") as f:
            f.write(str(value))
    except OSError as e:
        return e.errno or errno.EIO
    if fault and "readback" in fault:
        try:
            with open(path, "w") as f:
                f.write(str(fault["readback"]))
        except OSError:
            pass
    return 0


def errname(code: int) -> str:
    return errno.errorcode.get(code, str(code)) if code else "OK"


def write_json_atomic(path: str, data, mode=0o644):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path: str, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
