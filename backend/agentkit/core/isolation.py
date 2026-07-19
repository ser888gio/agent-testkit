"""Killable run isolation with a supervisor-owned sandbox.

The outer child owns the real sandbox and evaluates tests.  Agent code runs in
a nested worker against a generic RPC proxy.  On timeout the worker process
tree is destroyed *before* the supervisor snapshots the sandbox, so timeout
evidence cannot race a still-running agent.
"""

from __future__ import annotations

import ctypes
import importlib
import math
import multiprocessing
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from multiprocessing.connection import Connection, wait
from typing import Any

import cloudpickle

GRACE_SECONDS = 5.0
DEFAULT_MEMORY_MB = 2048
DEFAULT_CPU_SECONDS = 900

_WINDOWS_JOB_HANDLES: list[int] = []
_SCALAR_TYPES = (
    type(None),
    bool,
    bytes,
    date,
    datetime,
    datetime_time,
    float,
    int,
    str,
    timedelta,
)


@dataclass(frozen=True)
class IsolationFailure:
    error: str


def _apply_posix_limits(memory_mb: int, cpu_seconds: int) -> None:
    try:
        import resource
    except ImportError:  # pragma: no cover - Windows
        return

    for what, requested in (
        (resource.RLIMIT_AS, memory_mb * 1024 * 1024),
        (resource.RLIMIT_CPU, cpu_seconds),
    ):
        try:
            _, hard = resource.getrlimit(what)
            ceiling = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            # Lower the hard limit too.  Agent code runs under the same uid and
            # could otherwise raise the soft limit back to the old hard value.
            resource.setrlimit(what, (ceiling, ceiling))
        except (AttributeError, ValueError, OSError):
            pass


def _attach_windows_job(memory_mb: int, cpu_seconds: int) -> None:
    """Put this process in a kill-on-close job with CPU and memory ceilings."""
    if os.name != "nt":
        return

    from ctypes import wintypes

    class IOCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IOCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    info = ExtendedLimitInformation()
    info.BasicLimitInformation.PerProcessUserTimeLimit = cpu_seconds * 10_000_000
    info.BasicLimitInformation.LimitFlags = 0x2 | 0x100 | 0x2000
    info.ProcessMemoryLimit = memory_mb * 1024 * 1024
    if not kernel32.SetInformationJobObject(
        handle, 9, ctypes.byref(info), ctypes.sizeof(info)
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise ctypes.WinError(error)

    # Closing the last handle kills every process in the job.  Keeping the
    # handle process-local also makes an external TerminateProcess tree-safe.
    _WINDOWS_JOB_HANDLES.append(int(handle))


def _prepare_process(memory_mb: int, cpu_seconds: int) -> None:
    if os.name == "nt":
        _attach_windows_job(memory_mb, cpu_seconds)
        return
    os.setpgid(0, 0)
    _apply_posix_limits(memory_mb, cpu_seconds)


def _kill_process_tree(proc: Any) -> None:
    if proc is None:
        return
    if os.name != "nt" and proc.pid:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except (OSError, ValueError):
                pass
    else:
        try:
            proc.kill()
        except (OSError, ValueError):
            pass


def _resolve(
    root: Any, path: tuple[tuple[str, Any], ...], references: dict[int, Any]
) -> Any:
    value = root
    for kind, key in path:
        if kind == "ref":
            value = references[key]
        else:
            value = getattr(value, key) if kind == "attr" else value[key]
    return value


def _encode_remote(
    value: Any,
    path: tuple[tuple[str, Any], ...] | None,
    references: dict[int, Any],
) -> tuple[str, Any]:
    if callable(value):
        if path is None:
            reference = id(value)
            references[reference] = value
            path = (("ref", reference),)
        return ("method", path)
    if isinstance(value, _SCALAR_TYPES) or (
        isinstance(value, (frozenset, tuple))
        and all(isinstance(item, _SCALAR_TYPES) for item in value)
    ):
        return ("value", value)
    # Preserve normal Python reference semantics even if the containing list,
    # mapping, or attribute is later replaced.
    reference = id(value)
    references[reference] = value
    return ("proxy", (("ref", reference),))


def _decode_argument(root: Any, references: dict[int, Any], value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "remote-path":
        return _resolve(root, value[1], references)
    if isinstance(value, list):
        return [_decode_argument(root, references, item) for item in value]
    if isinstance(value, dict):
        return {
            key: _decode_argument(root, references, item) for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_decode_argument(root, references, item) for item in value)
    return value


def _handle_rpc(
    root: Any, references: dict[int, Any], message: tuple[Any, ...]
) -> tuple[bool, Any]:
    _, operation, path, args, kwargs = message
    try:
        if operation == "getattr":
            name = args[0]
            child_path = (*path, ("attr", name))
            result = _encode_remote(
                _resolve(root, child_path, references), child_path, references
            )
        elif operation == "setattr":
            setattr(
                _resolve(root, path, references),
                args[0],
                _decode_argument(root, references, args[1]),
            )
            result = ("value", None)
        elif operation == "getitem":
            key = _decode_argument(root, references, args[0])
            child_path = (*path, ("item", key))
            result = _encode_remote(
                _resolve(root, child_path, references), child_path, references
            )
        elif operation == "setitem":
            target = _resolve(root, path, references)
            target[_decode_argument(root, references, args[0])] = _decode_argument(
                root, references, args[1]
            )
            result = ("value", None)
        elif operation == "call":
            fn = _resolve(root, path, references)
            call_args = [_decode_argument(root, references, arg) for arg in args]
            call_kwargs = {
                key: _decode_argument(root, references, value)
                for key, value in kwargs.items()
            }
            result = _encode_remote(fn(*call_args, **call_kwargs), None, references)
        elif operation == "len":
            result = ("value", len(_resolve(root, path, references)))
        elif operation == "contains":
            result = (
                "value",
                _decode_argument(root, references, args[0])
                in _resolve(root, path, references),
            )
        elif operation == "iterate":
            target = _resolve(root, path, references)
            if isinstance(target, dict):
                result = ("value", list(target))
            else:
                result = (
                    "value",
                    [_encode_remote(item, None, references) for item in target],
                )
        else:  # pragma: no cover - protocol invariant
            raise ValueError(f"unknown sandbox RPC operation: {operation}")
        return True, result
    except Exception as exc:  # noqa: BLE001 - return the sandbox failure to the agent
        return False, f"{type(exc).__name__}: {exc}"


class _RemoteSession:
    def __init__(self, conn: Connection):
        self.conn = conn
        self.lock = threading.Lock()

    def request(
        self,
        operation: str,
        path: tuple[tuple[str, Any], ...],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        wire_args = tuple(_encode_argument(arg) for arg in args)
        wire_kwargs = {key: _encode_argument(value) for key, value in kwargs.items()}
        with self.lock:
            self.conn.send((time.monotonic(), operation, path, wire_args, wire_kwargs))
            ok, payload = self.conn.recv()
        if not ok:
            raise RuntimeError(payload)
        return _decode_remote(self, payload)


def _encode_argument(value: Any) -> Any:
    if isinstance(value, _RemoteObject):
        return ("remote-path", value._path)
    if isinstance(value, list):
        return [_encode_argument(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode_argument(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_encode_argument(item) for item in value)
    return value


def _decode_remote(session: _RemoteSession, encoded: tuple[str, Any]) -> Any:
    kind, payload = encoded
    if kind == "value":
        return payload
    if kind == "proxy":
        return _RemoteObject(session, payload)
    if kind == "method":
        return lambda *args, **kwargs: session.request("call", payload, *args, **kwargs)
    raise RuntimeError(f"unknown sandbox RPC value: {kind}")


class _RemoteObject:
    def __init__(self, session: _RemoteSession, path: tuple[tuple[str, Any], ...]):
        object.__setattr__(self, "_session", session)
        object.__setattr__(self, "_path", path)

    def __getattr__(self, name: str) -> Any:
        return self._session.request("getattr", self._path, name)

    def __setattr__(self, name: str, value: Any) -> None:
        self._session.request("setattr", self._path, name, value)

    def __getitem__(self, key: Any) -> Any:
        return self._session.request("getitem", self._path, key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._session.request("setitem", self._path, key, value)

    def __contains__(self, value: Any) -> bool:
        return bool(self._session.request("contains", self._path, value))

    def __iter__(self):
        values = self._session.request("iterate", self._path)
        for value in values:
            if isinstance(value, tuple) and value and value[0] in {"value", "proxy", "method"}:
                yield _decode_remote(self._session, value)
            else:
                yield value

    def __len__(self) -> int:
        return int(self._session.request("len", self._path))


def _agent_child(
    command: Connection,
    rpc: Connection,
    target: Any,
    endpoint: Any,
    memory_mb: int,
    cpu_seconds: int,
) -> None:  # pragma: no cover - subprocess
    try:
        _prepare_process(memory_mb, cpu_seconds)
        from agentkit.core.agent import build_agent

        sandbox = _RemoteObject(_RemoteSession(rpc), ())
        agent = build_agent(target, sandbox=sandbox, endpoint=endpoint)
        command.send(("ready", None))
        while True:
            kind, payload = command.recv()
            if kind == "close":
                return
            if kind == "turn":
                response = agent.run(cloudpickle.loads(payload))
                command.send(("result", cloudpickle.dumps(response)))
                continue
            if kind == "python":
                fn = cloudpickle.loads(payload)
                started = time.perf_counter()
                try:
                    fn(agent, sandbox)
                    outcome = ("passed", "", (time.perf_counter() - started) * 1000)
                except AssertionError as exc:
                    outcome = ("failed", str(exc), (time.perf_counter() - started) * 1000)
                except Exception as exc:  # noqa: BLE001 - evidence, not worker crash
                    outcome = ("error", str(exc), (time.perf_counter() - started) * 1000)
                command.send(("result", cloudpickle.dumps(outcome)))
                continue
            raise ValueError(f"unknown agent command: {kind}")
    except EOFError:
        return
    except Exception as exc:  # noqa: BLE001 - report startup/protocol failure
        try:
            command.send(("error", f"{type(exc).__name__}: {exc}"))
        except (EOFError, OSError, ValueError):
            pass


class _AgentController:
    def __init__(
        self,
        target: Any,
        endpoint: Any,
        sandbox: Any,
        worker_pid: Any,
        memory_mb: int,
        cpu_seconds: int,
    ):
        self._target = target
        self._endpoint = endpoint
        self._sandbox = sandbox
        self._worker_pid = worker_pid
        self._memory_mb = memory_mb
        self._cpu_seconds = cpu_seconds
        self._references: dict[int, Any] = {}
        self._ctx = multiprocessing.get_context("spawn")
        self._proc: Any = None
        self._command: Connection | None = None
        self._rpc: Connection | None = None

    def _service_until(self, deadline: float) -> tuple[str, Any]:
        assert self._command is not None and self._rpc is not None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout", None
            ready = wait((self._rpc, self._command), timeout=remaining)
            if not ready:
                return "timeout", None
            if self._rpc in ready:
                try:
                    message = self._rpc.recv()
                except (EOFError, OSError):
                    return "dead", None
                if message[0] > deadline:
                    return "timeout", None
                try:
                    self._rpc.send(
                        _handle_rpc(self._sandbox, self._references, message)
                    )
                except (EOFError, OSError):
                    return "dead", None
            if self._command in ready:
                try:
                    return self._command.recv()
                except (EOFError, OSError):
                    return "dead", None

    def _start(self, deadline: float) -> tuple[bool, str | None]:
        if self._proc is not None and self._proc.is_alive():
            return True, None
        parent_command, child_command = self._ctx.Pipe()
        parent_rpc, child_rpc = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=_agent_child,
            args=(
                child_command,
                child_rpc,
                self._target,
                self._endpoint,
                self._memory_mb,
                self._cpu_seconds,
            ),
        )
        try:
            proc.start()
        except Exception as exc:  # noqa: BLE001 - normalized by caller
            child_command.close()
            child_rpc.close()
            parent_command.close()
            parent_rpc.close()
            return False, f"{type(exc).__name__}: {exc}"
        child_command.close()
        child_rpc.close()
        self._proc = proc
        self._command = parent_command
        self._rpc = parent_rpc
        self._worker_pid.value = proc.pid or 0
        kind, payload = self._service_until(deadline)
        if kind == "ready":
            return True, None
        self.close(kill=True)
        return False, "timeout" if kind == "timeout" else str(payload or "agent process died")

    def _request(self, kind: str, payload: bytes, timeout_s: float) -> tuple[str, Any]:
        # Process startup is infrastructure overhead, not part of the test's
        # per-turn agent budget.  The outer parent already grants this bounded
        # grace in its hard deadline.
        ready, error = self._start(time.monotonic() + GRACE_SECONDS)
        if not ready:
            return "error", error
        assert self._command is not None
        deadline = time.monotonic() + timeout_s
        try:
            self._command.send((kind, payload))
        except (EOFError, OSError, ValueError) as exc:
            self.close(kill=True)
            return "error", f"{type(exc).__name__}: {exc}"
        message_kind, result = self._service_until(deadline)
        if message_kind == "result":
            try:
                return "result", cloudpickle.loads(result)
            except Exception as exc:  # noqa: BLE001 - malformed worker result
                self.close(kill=True)
                return "error", f"{type(exc).__name__}: {exc}"
        self.close(kill=True)
        if message_kind == "timeout":
            return "timeout", None
        return "error", result or "agent process died"

    def run_turn(self, input_value: Any, timeout_s: float) -> Any:
        from agentkit.core.agent import AgentResponse

        try:
            payload = cloudpickle.dumps(input_value)
        except Exception as exc:  # noqa: BLE001 - result must not escape run()
            return AgentResponse(error=f"{type(exc).__name__}: {exc}")
        kind, result = self._request("turn", payload, timeout_s)
        if kind == "result":
            return result
        if kind == "timeout":
            return AgentResponse(error="timeout")
        return AgentResponse(error=str(result))

    def run_python(self, fn_blob: bytes, timeout_s: float) -> tuple[str, str, float | None]:
        kind, result = self._request("python", fn_blob, timeout_s)
        if kind == "result":
            return result
        if kind == "timeout":
            return "error", "timeout", None
        return "error", str(result), None

    def close(self, kill: bool = False) -> None:
        command, rpc, proc = self._command, self._rpc, self._proc
        self._command = self._rpc = self._proc = None
        if command is not None and not kill:
            try:
                command.send(("close", None))
            except (EOFError, OSError, ValueError):
                pass
        if command is not None:
            command.close()
        if rpc is not None:
            rpc.close()
        if proc is not None:
            if not kill:
                proc.join(timeout=0.5)
            if proc.is_alive():
                _kill_process_tree(proc)
            proc.join(timeout=GRACE_SECONDS)
        self._worker_pid.value = 0


def _python_result(
    controller: _AgentController,
    sandbox: Any,
    request: dict[str, Any],
    redactor: Any,
    evidence: Any,
) -> Any:
    from agentkit.core.agent import AgentResponse
    from agentkit.core.runner import _now, _redact_assertions, _redact_evidence
    from agentkit.core.schema import AssertionResult, Status, TestResult

    started = _now()
    try:
        if sandbox is not None:
            sandbox.reset()
        outcome, detail, latency_ms = controller.run_python(
            request["fn"], request["timeout_s"]
        )
        if outcome == "passed":
            status = Status.passed
            assertions = [AssertionResult(name=request["id"], passed=True)]
            error = None
        elif outcome == "failed":
            status = Status.failed
            assertions = [AssertionResult(name=request["id"], passed=False, detail=detail)]
            error = None
        else:
            status = Status.error
            assertions = []
            error = detail
        request_evidence, response_evidence = _redact_evidence(
            evidence, redactor, "<python test>", AgentResponse(error=error)
        )
        return TestResult(
            test_id=request["id"],
            category=request["category"],
            risk=request["risk"],
            status=status,
            latency_ms=latency_ms,
            assertion_results=_redact_assertions(redactor, assertions),
            request=request_evidence,
            response=response_evidence,
            sandbox_diff=None,
            error=redactor.redact_text(error) if error else None,
            started_at=started,
            finished_at=_now(),
        )
    except Exception as exc:  # noqa: BLE001 - runner contract
        return TestResult(
            test_id=request["id"],
            category=request["category"],
            risk=request["risk"],
            status=Status.error,
            error=redactor.redact_text(str(exc)),
            started_at=started,
            finished_at=_now(),
        )


def _child(
    conn: Connection,
    target: Any,
    redactor: Any,
    endpoint: Any,
    preload: tuple[str, ...],
    memory_mb: int,
    cpu_seconds: int,
    worker_pid: Any,
) -> None:  # pragma: no cover - subprocess
    controller = None
    try:
        _prepare_process(memory_mb, cpu_seconds)
        for name in preload:
            importlib.import_module(name)

        from agentkit.core.runner import run_one
        from agentkit.core.sandbox import build_sandbox

        sandbox = build_sandbox(target.sandbox) if target.sandbox else None
        controller = _AgentController(
            target, endpoint, sandbox, worker_pid, memory_mb, cpu_seconds
        )
        conn.send(("ready", None))
        while True:
            message = conn.recv()
            if message is None:
                return
            kind, payload = message
            request = cloudpickle.loads(payload)
            if kind == "yaml":
                result = run_one(
                    None,
                    sandbox,
                    request,
                    redactor,
                    target.evidence,
                    run_turn=controller.run_turn,
                )
            elif kind == "python":
                result = _python_result(
                    controller, sandbox, request, redactor, target.evidence
                )
            else:
                raise ValueError(f"unknown isolated request: {kind}")
            conn.send(("result", cloudpickle.dumps(result)))
    except EOFError:
        return
    except Exception as exc:  # noqa: BLE001 - parent normalizes the failure
        try:
            conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except (EOFError, OSError, ValueError):
            pass
    finally:
        if controller is not None:
            controller.close()


class IsolatedRunner:
    """Runs a sequence of tests in one sandbox-owning child process."""

    def __init__(
        self,
        target: Any,
        redactor: Any,
        endpoint: Any = None,
        preload: tuple[str, ...] = (),
        *,
        memory_mb: int = DEFAULT_MEMORY_MB,
        cpu_seconds: int = DEFAULT_CPU_SECONDS,
    ):
        self._ctx = multiprocessing.get_context("spawn")
        self._worker_pid = self._ctx.Value("q", 0)
        self._args = (
            target,
            redactor,
            endpoint,
            preload,
            memory_mb,
            cpu_seconds,
            self._worker_pid,
        )
        self._proc: Any = None
        self._conn: Connection | None = None

    def _start(self, deadline: float) -> IsolationFailure | None:
        if self._conn is not None:
            return None
        parent, child = self._ctx.Pipe()
        proc = self._ctx.Process(target=_child, args=(child, *self._args))
        try:
            proc.start()
        except Exception as exc:  # noqa: BLE001 - runner must never raise
            parent.close()
            child.close()
            return IsolationFailure(f"{type(exc).__name__}: {exc}")
        child.close()
        self._proc = proc
        self._conn = parent
        remaining = deadline - time.monotonic()
        try:
            if remaining <= 0 or not parent.poll(remaining):
                self.close(kill=True)
                return IsolationFailure("timeout")
            kind, payload = parent.recv()
        except Exception as exc:  # noqa: BLE001 - normalize every IPC failure
            self.close(kill=True)
            return IsolationFailure(f"{type(exc).__name__}: {exc}")
        if kind != "ready":
            self.close(kill=True)
            return IsolationFailure(str(payload or "isolated child failed to start"))
        return None

    def _request(self, kind: str, payload: Any, deadline_s: float) -> Any | IsolationFailure:
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            return IsolationFailure("invalid isolation deadline")
        deadline = time.monotonic() + deadline_s
        failure = self._start(deadline)
        if failure is not None:
            return failure
        assert self._conn is not None
        try:
            encoded = cloudpickle.dumps(payload)
            self._conn.send((kind, encoded))
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._conn.poll(remaining):
                self.close(kill=True)
                return IsolationFailure("timeout")
            message_kind, result = self._conn.recv()
            if message_kind != "result":
                return IsolationFailure(str(result or "isolated child died"))
            return cloudpickle.loads(result)
        except Exception as exc:  # noqa: BLE001 - runner must never raise
            self.close(kill=True)
            return IsolationFailure(f"{type(exc).__name__}: {exc}")

    def run_test(self, test: Any, deadline_s: float) -> Any | IsolationFailure:
        return self._request("yaml", test, deadline_s)

    def run_python_test(self, test: Any, deadline_s: float) -> Any | IsolationFailure:
        try:
            request = {
                "id": test.id,
                "category": test.category,
                "risk": test.risk,
                "timeout_s": test.timeout_s,
                "fn": cloudpickle.dumps(test.fn),
            }
        except Exception as exc:  # noqa: BLE001 - runner must never raise
            return IsolationFailure(f"{type(exc).__name__}: {exc}")
        return self._request("python", request, deadline_s)

    def close(self, kill: bool = False) -> None:
        conn, proc = self._conn, self._proc
        self._conn = self._proc = None
        if conn is not None and not kill:
            try:
                conn.send(None)
            except (EOFError, OSError, ValueError):
                pass
        if conn is not None:
            conn.close()
        if proc is not None:
            if not kill:
                proc.join(timeout=0.5)
            if proc.is_alive():
                if os.name != "nt" and self._worker_pid.value:
                    try:
                        os.killpg(self._worker_pid.value, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                _kill_process_tree(proc)
            proc.join(timeout=GRACE_SECONDS)
        self._worker_pid.value = 0
