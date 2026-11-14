"""Run a Windows process with a zero-capability AppContainer token."""

import ctypes as c
import os
import shutil
import subprocess
from contextlib import contextmanager
from ctypes import wintypes as w
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4


class Security(c.Structure):
    _fields_ = [
        ("sid", c.c_void_p),
        ("capabilities", c.c_void_p),
        ("count", w.DWORD),
        ("reserved", w.DWORD),
    ]


class Startup(c.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        *[(x, w.LPWSTR) for x in ("reserved", "desktop", "title")],
        *[(x, w.DWORD) for x in ("x", "y", "xs", "ys", "xc", "yc", "fill", "flags")],
        ("show", w.WORD),
        ("reserved_size", w.WORD),
        ("reserved_data", c.c_void_p),
        *[(x, w.HANDLE) for x in ("stdin", "stdout", "stderr")],
        ("attributes", c.c_void_p),
    ]


class Process(c.Structure):
    _fields_ = [
        ("process", w.HANDLE),
        ("thread", w.HANDLE),
        ("pid", w.DWORD),
        ("tid", w.DWORD),
    ]


def configure(dll, name, result, *args):
    function = getattr(dll, name)
    function.argtypes = list(args)
    function.restype = result
    return function


p = c.c_void_p
k = c.WinDLL("kernel32", use_last_error=True)
u = c.WinDLL("userenv")
create = configure(
    u,
    "CreateAppContainerProfile",
    c.c_long,
    w.LPCWSTR,
    w.LPCWSTR,
    w.LPCWSTR,
    p,
    w.DWORD,
    c.POINTER(p),
)
delete = configure(u, "DeleteAppContainerProfile", c.c_long, w.LPCWSTR)
free = configure(c.WinDLL("advapi32"), "FreeSid", p, p)
init = configure(
    k,
    "InitializeProcThreadAttributeList",
    w.BOOL,
    p,
    w.DWORD,
    w.DWORD,
    c.POINTER(c.c_size_t),
)
update = configure(
    k, "UpdateProcThreadAttribute", w.BOOL, p, w.DWORD, c.c_size_t, p, c.c_size_t, p, p
)
cleanup = configure(k, "DeleteProcThreadAttributeList", None, p)
launch = configure(
    k,
    "CreateProcessW",
    w.BOOL,
    w.LPCWSTR,
    w.LPWSTR,
    p,
    p,
    w.BOOL,
    w.DWORD,
    p,
    w.LPCWSTR,
    c.POINTER(Startup),
    c.POINTER(Process),
)
wait = configure(k, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)
get_exit = configure(k, "GetExitCodeProcess", w.BOOL, w.HANDLE, c.POINTER(w.DWORD))
terminate = configure(k, "TerminateProcess", w.BOOL, w.HANDLE, w.UINT)
close = configure(k, "CloseHandle", w.BOOL, w.HANDLE)


@contextmanager
def isolated_runtime(python, modules):
    """Stage only trusted runtime files under a temporary, per-run SID."""
    name = "pdx." + uuid4().hex
    sid = p()
    if create(name, name, "Archive worker", None, 0, c.byref(sid)):
        raise OSError("AppContainer profile creation failed")
    try:
        with TemporaryDirectory(prefix="pdx-archive-runtime-") as directory:
            root = Path(directory)
            base = Path(python).resolve().parent
            for item in base.iterdir():
                if item.name == Path(python).name or item.suffix.lower() == ".dll":
                    shutil.copy2(item, root)
            shutil.copytree(base / "DLLs", root / "DLLs")
            shutil.copytree(
                base / "Lib",
                root / "Lib",
                ignore=shutil.ignore_patterns(
                    "site-packages", "__pycache__", "test", "tests"
                ),
            )
            for source in modules:
                shutil.copytree(
                    source,
                    root / source.name,
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
            scratch = root / "scratch"
            scratch.mkdir()
            grant_access(root, sid, "(OI)(CI)(RX)")
            grant_access(scratch, sid, "(OI)(CI)(M)")
            yield root, scratch, sid
    finally:
        free(sid)
        if delete(name):
            raise OSError("AppContainer profile cleanup failed")


def grant_access(path, sid, rights):
    sid_text = w.LPWSTR()
    convert = configure(
        c.WinDLL("advapi32", use_last_error=True),
        "ConvertSidToStringSidW",
        w.BOOL,
        p,
        c.POINTER(w.LPWSTR),
    )
    if not convert(sid, c.byref(sid_text)):
        raise c.WinError(c.get_last_error())
    try:
        subprocess.run(
            ["icacls.exe", str(path), "/grant", "*" + sid_text.value + ":" + rights],
            capture_output=True,
            check=True,
            timeout=15,
            creationflags=0x08000000,
        )
    finally:
        configure(k, "LocalFree", p, p)(c.cast(sid_text, p))


def launch_isolated(target, args, root, sid, *, assign, timeout, check_active=None):
    """Create suspended, attach hard resource limits, then start the process."""
    size = c.c_size_t()
    init(None, 1, 0, c.byref(size))
    attributes = c.create_string_buffer(size.value)
    if not init(attributes, 1, 0, c.byref(size)):
        raise c.WinError(c.get_last_error())
    child = Process()
    try:
        capability = Security(sid, None, 0, 0)
        if not update(
            attributes,
            0,
            0x20009,
            c.byref(capability),
            c.sizeof(capability),
            None,
            None,
        ):
            raise c.WinError(c.get_last_error())
        startup = Startup()
        startup.cb = c.sizeof(startup)
        startup.attributes = c.cast(attributes, p)
        command = c.create_unicode_buffer(subprocess.list2cmdline([str(target), *args]))
        variables = {
            name: os.environ[name]
            for name in (
                "SystemRoot",
                "SystemDrive",
                "USERPROFILE",
                "LOCALAPPDATA",
                "APPDATA",
            )
            if name in os.environ
        }
        variables.update(TEMP=str(root / "scratch"), TMP=str(root / "scratch"))
        environment = c.create_unicode_buffer(
            "\0".join(
                f"{key}={value}"
                for key, value in sorted(
                    variables.items(), key=lambda item: item[0].lower()
                )
            )
            + "\0\0"
        )
        if not launch(
            str(target),
            command,
            None,
            None,
            False,
            0x08080404,
            environment,
            str(root),
            c.byref(startup),
            c.byref(child),
        ):
            raise c.WinError(c.get_last_error())
        try:
            assign(child.process)
            resume = configure(k, "ResumeThread", w.DWORD, w.HANDLE)
            if resume(child.thread) == 0xFFFFFFFF:
                raise c.WinError(c.get_last_error())
            deadline = monotonic() + timeout
            while True:
                if check_active is not None:
                    check_active()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("AppContainer worker deadline expired")
                interval = min(remaining, 0.25) if check_active else remaining
                status = wait(child.process, max(1, int(interval * 1000)))
                if status == 0:
                    break
                if status != 258:
                    raise c.WinError(c.get_last_error())
            code = w.DWORD()
            if not get_exit(child.process, c.byref(code)):
                raise c.WinError(c.get_last_error())
            return code.value
        finally:
            if wait(child.process, 0) != 0:
                terminate(child.process, 24)
                wait(child.process, 5000)
            close(child.thread)
            close(child.process)
    finally:
        cleanup(attributes)
