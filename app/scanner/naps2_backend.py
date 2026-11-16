import shutil
import subprocess
import sys
import threading
from pathlib import Path
from app.scanner.base import Scanner, ScanOptions, ScannerBackend, ScannerError


SCAN_TIMEOUT_SECONDS = 900
DISCOVERY_TIMEOUT_SECONDS = 45
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Naps2Backend(ScannerBackend):
    """Drives physical scanners through the NAPS2 Console CLI (TWAIN preferred, WIA fallback)."""

    def __init__(self, configured_path=""):
        self._lock = threading.Lock()
        self._process = None
        self._canceled = False
        self.executable = self._resolve(configured_path)
        self.diagnostic = "ready" if self.available else "engine_missing"
        self.diagnostic_detail = ""

    @staticmethod
    def _resolve(configured_path):
        bundled = Path(sys.executable).resolve().parent / "tools" / "naps2" / "App" / "NAPS2.Console.exe"
        candidates = [bundled, configured_path, shutil.which("naps2.console"), shutil.which("NAPS2.Console"),
                      r"C:\Program Files\NAPS2\NAPS2.Console.exe",
                      r"C:\Program Files (x86)\NAPS2\NAPS2.Console.exe"]
        return next((str(Path(p)) for p in candidates if p and Path(p).is_file()), None)

    @property
    def available(self):
        return self.executable is not None

    def discover(self, drivers=None):
        """List device names per driver. TWAIN is queried first so it wins when a
        device is exposed by both drivers (e.g. the HP ScanJet N7000 snw1)."""
        if not self.available:
            self.diagnostic = "engine_missing"
            return []
        found = []
        errors = []
        for driver in drivers or ("twain", "wia"):
            try:
                run = subprocess.run([self.executable, "--listdevices", "--driver", driver],
                                     capture_output=True, text=True,
                                     timeout=DISCOVERY_TIMEOUT_SECONDS, creationflags=NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(str(exc))
                continue
            if run.returncode:
                errors.append((run.stderr or run.stdout or f"{driver} discovery exited with code {run.returncode}").strip())
            for line in (run.stdout or "").splitlines():
                name = line.strip()
                if not self._is_device_line(name):
                    continue
                if any(existing.name == name and existing.driver == driver for existing in found):
                    continue
                found.append(Scanner(name, driver))
        detail = " ".join(errors).lower()
        self.diagnostic_detail = " ".join(errors)[:300]
        if found:
            self.diagnostic = "ready"
        elif any(word in detail for word in ("driver not found", "no driver", "twain source manager", "driver is not installed")):
            self.diagnostic = "driver_missing"
        elif errors and len(errors) == len(drivers or ("twain", "wia")):
            self.diagnostic = "engine_error"
        else:
            self.diagnostic = "no_scanner"
        return found

    @staticmethod
    def _is_device_line(name):
        lowered = name.lower()
        if lowered.startswith(("error", "warning", "devices", "searching", "naps2", "usage")):
            return False
        return "copyright" not in lowered

    def scan(self, options: ScanOptions, output: Path):
        if not self.available:
            raise ScannerError("NAPS2 scanning engine is missing. Reinstall ScaNow or set an external NAPS2 Console path in Settings.")
        # One scan operation: feeder/duplex drain the whole ADF; glass captures one page.
        number = max(1, options.pages) if options.source == "glass" else 1
        args = [self.executable, "-o", str(output), "-f", "--noprofile",
                "--driver", options.scanner.driver, "--device", options.scanner.name,
                "--source", options.source, "--dpi", str(options.dpi),
                "--bitdepth", options.color,
                "--number", str(number)]
        if options.paper != "auto":
            args.extend(("--pagesize", options.paper))
        if options.deskew:
            args.append("--deskew")
        self._canceled = False
        with self._lock:
            if self._process:
                raise ScannerError("A scan is already running.")
            try:
                self._process = subprocess.Popen(args, stdout=subprocess.PIPE,
                                                 stderr=subprocess.PIPE, text=True,
                                                 creationflags=NO_WINDOW)
            except OSError as exc:
                raise ScannerError(f"Could not start NAPS2: {exc}") from exc
        try:
            stdout, stderr = self._process.communicate(timeout=SCAN_TIMEOUT_SECONDS)
            code = self._process.returncode
        except subprocess.TimeoutExpired:
            self._terminate()
            raise ScannerError("The scan was stopped because it ran too long. Previously scanned pages were kept.")
        finally:
            with self._lock:
                self._process = None
        if self._canceled:
            raise ScannerError("Scan canceled.")
        if code or not output.is_file():
            raise ScannerError(self._friendly_error(stderr or stdout or "", code, output.is_file()))
        return output

    @staticmethod
    def _friendly_error(detail, code, output_exists):
        text = (detail or "").strip()
        lowered = text.lower()
        messages = [
            (("feeder", "empty"), "The document feeder is empty. Load pages into the ADF and try again."),
            (("jam", "misfeed", "paper stop"),
             "The scanner reported a paper jam or interruption. Clear the device and try again."),
            (("cancel", "canceled"), "Scan canceled."),
            (("device not found", "no device", "not found"),
             "The selected scanner was not found. Refresh the scanner list or check the connection."),
            (("offline", "not connected", "disconnect", "communication", "unreachable", "power"),
             "The scanner appears to be disconnected or powered off."),
            (("busy", "in use", "locked"),
             "The scanner is busy or in use by another application."),
            (("timeout", "timed out"),
             "The scanner driver timed out. Try again, possibly with a lower resolution."),
            (("driver",), "The scanner driver reported a problem."),
        ]
        for needles, message in messages:
            if any(needle in lowered for needle in needles):
                return f"{message} Previously scanned pages were kept."
        if not text:
            return f"NAPS2 exited with code {code} and produced no scanned pages. Previously scanned pages were kept."
        return f"NAPS2 reported an error: {text[:400]}"

    def _terminate(self):
        with self._lock:
            process = self._process
            self._canceled = True
        if process:
            self._kill(process)

    def cancel(self):
        with self._lock:
            process = self._process
            if not process:
                return
            self._canceled = True
        self._kill(process)

    @staticmethod
    def _kill(process):
        try:
            process.kill()
        except OSError:
            pass
