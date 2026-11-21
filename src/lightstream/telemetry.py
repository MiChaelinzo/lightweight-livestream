"""System telemetry for the dashboard and the optimizer. Never raises.

TelemetrySampler has no threads: the caller calls tick() (or tick_if_due())
on its own timer. Every reader is wrapped, so a missing file, a missing tool
or a parse error becomes None for that field, with the reason kept in
sampler.unavailable. All I/O goes through injected callables so tests run on
fake /proc text and a fake clock. Readings on real Windows, macOS and GPU
machines are UNVERIFIED; the Linux parsing is covered by tests on fake text.
"""

import glob
import os
import subprocess
import time
from collections import deque, namedtuple

from .config import detect_os

Sample = namedtuple(
    "Sample", "cpu_percent ram_percent ram_used_mb cpu_temp_c gpu_percent "
              "gpu_temp_c process_rss_mb")
UNKNOWN_SAMPLE = Sample(None, None, None, None, None, None, None)

POLL_SECONDS = 2
HISTORY_LIMIT = 150             # 5 minutes of samples at the default interval
GPU_CACHE_SECONDS = 5           # nvidia-smi is a process launch: ask rarely
GPU_TIMEOUT_SECONDS = 2
NVIDIA_SMI = "nvidia-smi"
NVIDIA_SMI_QUERY = ["--query-gpu=utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits"]
KIB_PER_MIB = 1024
BYTES_PER_MIB = 1024 * 1024
MILLIDEGREES = 1000.0
CPU_HWMON_NAMES = ("coretemp", "k10temp", "zenpower", "cpu_thermal")
CPU_THERMAL_TYPES = ("x86_pkg_temp", "cpu_thermal", "cpu-thermal", "soc_thermal")
FIELDS = Sample._fields


def _read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def parse_proc_stat(text):
    """(busy, total) jiffies from the first 'cpu' line of /proc/stat."""
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "cpu":
            values = [int(v) for v in parts[1:9]]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            return total - idle, total
    raise ValueError("no 'cpu' line in /proc/stat")


def parse_meminfo(text):
    """(percent used, MiB used) from /proc/meminfo text."""
    fields = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            fields[name.strip()] = int(parts[0])
    total = fields["MemTotal"]
    used = total - fields["MemAvailable"]
    return 100.0 * used / total, used / KIB_PER_MIB


def parse_vmrss_mb(text):
    """MiB from the VmRSS line of /proc/<pid>/status."""
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / KIB_PER_MIB
    raise ValueError("no VmRSS line")


def parse_nvidia_smi(text):
    """(gpu percent, gpu temperature C) from the first csv line."""
    first = text.strip().splitlines()[0]
    util, temp = (float(v) for v in first.split(","))
    return util, temp


class TelemetrySampler:
    """Collect one Sample per tick into a bounded history."""

    def __init__(self, os_name=None, clock=time.monotonic, read_text=_read_text,
                 find_paths=glob.glob, run=subprocess.run, which=None,
                 windows_cpu_times=None, windows_memory=None, pid=None,
                 interval=POLL_SECONDS):
        import shutil
        self.os_name = os_name or detect_os()
        self.clock = clock
        self.read_text = read_text
        self.find_paths = find_paths
        self.run = run
        self.which = which or shutil.which
        self.windows_cpu_times = windows_cpu_times or _windows_cpu_times
        self.windows_memory = windows_memory or _windows_memory
        self.pid = pid                 # process whose RSS is reported (ffmpeg)
        self.interval = interval
        self.history = deque(maxlen=HISTORY_LIMIT)
        self.unavailable = {}          # field name -> why it is None
        self._last_cpu = None
        self._last_tick = None
        self._gpu_at = None
        self._gpu_value = (None, None)

    @property
    def latest(self):
        return self.history[-1] if self.history else UNKNOWN_SAMPLE

    def due(self):
        return self._last_tick is None or self.clock() - self._last_tick >= self.interval

    def tick_if_due(self):
        """A new Sample when the interval has passed, else None."""
        return self.tick() if self.due() else None

    def tick(self):
        self._last_tick = self.clock()
        self.unavailable = {}
        cpu = self._guard(("cpu_percent",), self._cpu_percent)
        ram_percent, ram_mb = self._guard(("ram_percent", "ram_used_mb"), self._memory)
        gpu_percent, gpu_temp = self._guard(("gpu_percent", "gpu_temp_c"), self._gpu)
        sample = Sample(
            cpu, ram_percent, ram_mb,
            self._guard(("cpu_temp_c",), self._cpu_temp),
            gpu_percent, gpu_temp,
            self._guard(("process_rss_mb",), self._process_rss))
        self.history.append(sample)
        return sample

    def _guard(self, fields, reader):
        """Run reader; on any failure return None for each field and record why."""
        try:
            value = reader()
        except Exception as exc:  # a reader must never break the caller
            value = None
            reason = "%s: %s" % (type(exc).__name__, exc)
        else:
            reason = "not available on this system"
        if value is None:
            for name in fields:
                self.unavailable[name] = reason
            return None if len(fields) == 1 else (None,) * len(fields)
        return value

    # -- readers: return a value, or None when the platform has no source ----
    def _cpu_percent(self):
        if self.os_name == "linux":
            busy, total = parse_proc_stat(self.read_text("/proc/stat"))
        elif self.os_name == "windows":
            idle, kernel, user = self.windows_cpu_times()
            total = kernel + user          # kernel time includes idle time
            busy = total - idle
        else:
            return None
        previous, self._last_cpu = self._last_cpu, (busy, total)
        if previous is None or total <= previous[1]:
            return None                    # needs two readings for a delta
        return 100.0 * (busy - previous[0]) / (total - previous[1])

    def _memory(self):
        if self.os_name == "linux":
            return parse_meminfo(self.read_text("/proc/meminfo"))
        if self.os_name == "windows":
            total, available = self.windows_memory()
            used = total - available
            return 100.0 * used / total, used / BYTES_PER_MIB
        return None

    def _cpu_temp(self):
        if self.os_name != "linux":
            return None                    # macOS and Windows: no safe stdlib source
        readings = []
        for path in self.find_paths("/sys/class/hwmon/hwmon*/name"):
            if self.read_text(path).strip() in CPU_HWMON_NAMES:
                readings.append(self._millidegrees(
                    os.path.join(os.path.dirname(path), "temp1_input")))
        for path in self.find_paths("/sys/class/thermal/thermal_zone*/type"):
            if self.read_text(path).strip() in CPU_THERMAL_TYPES:
                readings.append(self._millidegrees(
                    os.path.join(os.path.dirname(path), "temp")))
        readings = [r for r in readings if r is not None]
        return max(readings) if readings else None

    def _millidegrees(self, path):
        try:
            return int(self.read_text(path).strip()) / MILLIDEGREES
        except (OSError, ValueError):
            return None

    def _gpu(self):
        """nvidia-smi only when installed; the result (even a failure) is
        cached for GPU_CACHE_SECONDS."""
        now = self.clock()
        if self._gpu_at is not None and now - self._gpu_at < GPU_CACHE_SECONDS:
            return self._gpu_value if self._gpu_value[0] is not None else None
        self._gpu_at = now
        self._gpu_value = (None, None)
        exe = self.which(NVIDIA_SMI)
        if not exe:
            return None
        result = self.run([exe] + NVIDIA_SMI_QUERY, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True,
                          timeout=GPU_TIMEOUT_SECONDS)
        self._gpu_value = parse_nvidia_smi(result.stdout or "")
        return self._gpu_value

    def _process_rss(self):
        if self.os_name != "linux" or not self.pid:
            return None
        return parse_vmrss_mb(self.read_text("/proc/%d/status" % self.pid))


def _windows_cpu_times():
    """(idle, kernel, user) 100ns ticks from GetSystemTimes. Windows only."""
    import ctypes
    from ctypes import wintypes
    idle, kernel, user = (wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME())
    if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError("GetSystemTimes failed")
    return tuple((f.dwHighDateTime << 32) | f.dwLowDateTime for f in (idle, kernel, user))


def _windows_memory():
    """(total, available) bytes from GlobalMemoryStatusEx. Windows only."""
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return status.ullTotalPhys, status.ullAvailPhys
