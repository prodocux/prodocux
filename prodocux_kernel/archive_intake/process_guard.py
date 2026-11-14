"""Windows hard limits for a trusted Python worker bootstrap."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from .decoders import ArchiveError


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong),
        ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def run_archive_worker(
    args,
    *,
    wall_seconds,
    cpu_seconds,
    memory_bytes,
    observe_peak=None,
    network_isolated=False,
    check_active=None,
):
    """Enforce CPU, memory, process count and wall time for the built-in worker."""
    if os.name != "nt":
        raise ArchiveError("PROFILE_UNQUALIFIED")
    if not (
        0 < wall_seconds <= 300
        and 0 < cpu_seconds <= 300
        and 0 < memory_bytes <= 1 << 30
    ):
        raise ArchiveError("MALFORMED_REQUEST")
    kernel = _kernel()
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ArchiveError("PROFILE_UNQUALIFIED")
    process = None
    assigned = False
    try:
        limits = _ExtendedLimits()
        # KILL_ON_JOB_CLOSE, PROCESS_MEMORY, ACTIVE_PROCESS, PROCESS_TIME.
        limits.basic.flags = 0x2000 | 0x100 | 0x8 | 0x2
        limits.basic.process_time = int(cpu_seconds * 10_000_000)
        limits.basic.active_processes = 1
        limits.process_memory = memory_bytes
        if not kernel.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            raise ArchiveError("PROFILE_UNQUALIFIED")
        if network_isolated:
            return _isolated_read(
                kernel, job, args, wall_seconds, observe_peak, check_active
            )
        bootstrap = (
            "import sys; "
            "sys.stdin.buffer.read(1) == b'1' or sys.exit(1); "
            f"sys.path[:] = {sys.path!r}; "
            "from prodocux_kernel.archive_intake.worker import main; main()"
        )
        # The Windows venv launcher can spawn the real interpreter as a
        # second process. Use the base interpreter with this installation's
        # module search path so the one-process job works from a wheel.
        process = subprocess.Popen(
            [sys._base_executable, "-B", "-I", "-S", "-c", bootstrap, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assigned = bool(
            kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle)))
        )
        if not assigned:
            raise ArchiveError("PROFILE_UNQUALIFIED")
        try:
            output, _ = process.communicate(b"1", timeout=wall_seconds)
        except subprocess.TimeoutExpired as exc:
            raise ArchiveError("EXECUTION_UNKNOWN") from exc
        if process.returncode != 0:
            raise ArchiveError("EXECUTION_UNKNOWN")
        if observe_peak is not None:
            measured = _ExtendedLimits()
            if (
                not kernel.QueryInformationJobObject(
                    job, 9, ctypes.byref(measured), ctypes.sizeof(measured), None
                )
                or not measured.peak_process
            ):
                raise ArchiveError("EXECUTION_UNKNOWN")
            observe_peak(measured.peak_process)
        return output
    finally:
        if process is not None and process.poll() is None:
            if assigned:
                kernel.TerminateJobObject(job, 1)
            else:
                process.kill()
            kernel.CloseHandle(job)
            process.communicate(timeout=5)
        else:
            kernel.CloseHandle(job)


def _isolated_read(kernel, job, args, wall_seconds, observe_peak, check_active):
    import json

    import pypdf
    import rfc8785

    from ._appcontainer import isolated_runtime, launch_isolated

    package = Path(__file__).resolve().parent
    modules = [
        package,
        Path(rfc8785.__file__).resolve().parent,
        Path(pypdf.__file__).resolve().parent,
    ]
    docx_leaf = args[3] == "resolve" and (
        json.loads(args[4])["chain"][-1]["selector"]["display_name"].lower().endswith(".docx")
    )
    if docx_leaf:
        import docx
        import lxml
        import typing_extensions

        modules.extend(
            Path(module.__file__).resolve().parent for module in (docx, lxml)
        )
    with isolated_runtime(sys._base_executable, modules) as (root, scratch, sid):
        shutil.copyfile(args[0], scratch / "source")
        shutil.copyfile(
            package.parent / "intake" / "text_projection.py",
            root / "archive_intake" / "_text_projection.py",
        )
        intake = root / "prodocux_kernel" / "intake"
        intake.mkdir(parents=True)
        for name in (
            "errors.py",
            "pdf.py",
            "pdf_projection.py",
            "projection_validate.py",
        ):
            shutil.copyfile(package.parent / "intake" / name, intake / name)
        if docx_leaf:
            for name in ("archive.py", "docx.py"):
                shutil.copyfile(package.parent / "intake" / name, intake / name)
            shutil.copyfile(typing_extensions.__file__, root / "typing_extensions.py")
        output = scratch / "result"
        bootstrap = (
            "import sys,tempfile; "
            "sys.path.insert(0,sys.argv.pop(1)); "
            "tempfile.tempdir=sys.argv.pop(1); "
            "from archive_intake.worker import main; "
            "out=open(sys.argv.pop(1),'w',encoding='utf-8'); "
            "sys.stdout=out; main(); out.close()"
        )

        def assign(handle):
            if not kernel.AssignProcessToJobObject(job, handle):
                raise ArchiveError("PROFILE_UNQUALIFIED")

        try:
            code = launch_isolated(
                root / Path(sys._base_executable).name,
                [
                    "-I",
                    "-S",
                    "-B",
                    "-c",
                    bootstrap,
                    str(root),
                    str(scratch),
                    str(output),
                    str(scratch / "source"),
                    *args[1:],
                ],
                root,
                sid,
                assign=assign,
                timeout=wall_seconds,
                check_active=check_active,
            )
            if code or output.stat().st_size > 2 << 20:
                raise ArchiveError("EXECUTION_UNKNOWN")
            if observe_peak is not None:
                measured = _ExtendedLimits()
                if (
                    not kernel.QueryInformationJobObject(
                        job, 9, ctypes.byref(measured), ctypes.sizeof(measured), None
                    )
                    or not measured.peak_process
                ):
                    raise ArchiveError("EXECUTION_UNKNOWN")
                observe_peak(measured.peak_process)
            return output.read_bytes()
        except OSError as error:
            raise ArchiveError("EXECUTION_UNKNOWN") from error
