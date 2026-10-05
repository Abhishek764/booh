"""Optional local TabPFN SDK boundary, in a bounded offline worker process."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import logging
import math
import multiprocessing
import os
import re
import resource
import socket
import stat
import sys
import tempfile
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any

from ml.prediction.contracts import (
    MAX_SLEEP_MINUTES,
    ModelInput,
    ModelProvenance,
    NumericalPrediction,
    PredictionError,
    TrainingPayload,
    finite_number,
)

SDK_VERSION = "9.1.0"
MAX_CHECKPOINT_BYTES = 512 * 1024 * 1024
_WORKER_SLOTS = BoundedSemaphore(2)


class _OfflineSocket(socket.socket):
    def __init__(
        self, family: int = socket.AF_INET, type: int = socket.SOCK_STREAM,
        proto: int = 0, fileno: int | None = None,
    ) -> None:
        if family in {socket.AF_INET, socket.AF_INET6}:
            raise PredictionError("model_unavailable")
        super().__init__(family, type, proto, fileno)


@dataclass(frozen=True, slots=True, repr=False)
class TabPFNConfig:
    """Server/operator configuration only; never populated from browser input."""

    regressor_checkpoint: Path
    classifier_checkpoint: Path
    regressor_sha256: str
    classifier_sha256: str
    fit_timeout_seconds: float = 120.0
    predict_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        for path, digest in (
            (self.regressor_checkpoint, self.regressor_sha256),
            (self.classifier_checkpoint, self.classifier_sha256),
        ):
            if (
                not isinstance(path, Path) or not path.is_absolute()
                or path.suffix != ".ckpt" or path.is_symlink()
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise PredictionError("invalid_model_configuration")
            try:
                info = path.stat()
            except OSError:
                raise PredictionError("model_unavailable") from None
            if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_CHECKPOINT_BYTES:
                raise PredictionError("invalid_model_configuration")
        finite_number(self.fit_timeout_seconds, 0.1, 180.0, code="invalid_model_configuration")
        finite_number(self.predict_timeout_seconds, 0.1, 30.0, code="invalid_model_configuration")


def _verified_copy(source: Path, destination: Path, expected_digest: str) -> None:
    """Copy/hash into a private directory; SDK cannot auto-download a missing path."""

    digest = hashlib.sha256()
    consumed = 0
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        while block := incoming.read(65536):
            consumed += len(block)
            if consumed > MAX_CHECKPOINT_BYTES:
                raise PredictionError("invalid_model_configuration")
            digest.update(block)
            outgoing.write(block)
    if consumed == 0 or digest.hexdigest() != expected_digest:
        raise PredictionError("invalid_model_configuration")


@dataclass(slots=True, repr=False)
class _FittedPair:
    # SDK/NumPy types are confined here; the rest of BOOH uses typed contracts.
    regressor: Any
    classifier: Any
    numpy: Any


def _fit_sdk(payload: TrainingPayload, regressor_path: Path, classifier_path: Path) -> _FittedPair:
    if importlib.metadata.version("tabpfn") != SDK_VERSION:
        raise PredictionError("model_unavailable")
    numpy = importlib.import_module("numpy")
    torch = importlib.import_module("torch")
    sdk = importlib.import_module("tabpfn")
    constants = importlib.import_module("tabpfn.constants")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    options = {
        "device": "cpu", "n_estimators": 2, "random_state": 0,
        "n_preprocessing_jobs": 1, "fit_mode": "fit_preprocessors",
        "ignore_pretraining_limits": False, "show_progress_bar": False,
    }
    regressor = sdk.TabPFNRegressor.create_default_for_version(
        constants.ModelVersion.V2, model_path=regressor_path, **options,
    )
    classifier = sdk.TabPFNClassifier.create_default_for_version(
        constants.ModelVersion.V2, model_path=classifier_path, **options,
    )
    inputs = numpy.asarray(payload.rows, dtype="float64")
    regressor.fit(inputs, numpy.asarray(payload.remaining_minutes, dtype="float64"))
    classifier.fit(inputs, numpy.asarray(payload.wake_labels, dtype="int64"))
    return _FittedPair(regressor, classifier, numpy)


def _predict_pair(pair: _FittedPair, values: tuple[float, ...]) -> NumericalPrediction:
    inputs = pair.numpy.asarray([values], dtype="float64")
    regression = pair.regressor.predict(inputs)
    probabilities = pair.classifier.predict_proba(inputs)
    if getattr(regression, "shape", None) != (1,) or getattr(probabilities, "shape", None) != (1, 2):
        raise PredictionError("invalid_model_output")
    classes = [finite_number(value, 0, 1, code="invalid_model_output") for value in pair.classifier.classes_]
    if len(classes) != 2 or set(classes) != {0.0, 1.0}:
        raise PredictionError("invalid_model_output")
    scores = [finite_number(value, 0, 1, code="invalid_model_output") for value in probabilities[0]]
    if len(scores) != 2 or not math.isclose(sum(scores), 1.0, abs_tol=1e-6):
        raise PredictionError("invalid_model_output")
    return NumericalPrediction(
        finite_number(regression[0], 0, MAX_SLEEP_MINUTES, code="invalid_model_output"),
        scores[classes.index(1.0)],
    )


def _offline_worker(connection: Connection, config: TabPFNConfig, payload: TrainingPayload, directory: str) -> None:
    # Spawn, rather than fork, prevents inherited service sessions/family state.
    # A clean private working directory also prevents the SDK reading app .env.
    os.chdir(directory)
    os.environ.clear()
    os.environ.update({
        "HOME": directory, "HF_HOME": directory, "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1", "TABPFN_NO_BROWSER": "1",
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    })
    logging.disable(logging.CRITICAL)
    quiet = open(os.devnull, "w")
    os.dup2(quiet.fileno(), 1)
    os.dup2(quiet.fileno(), 2)
    sys.stdout = sys.stderr = quiet
    setattr(socket, "socket", _OfflineSocket)
    hard = resource.getrlimit(resource.RLIMIT_AS)[1]
    budget = 4 * 1024**3 if hard == resource.RLIM_INFINITY else min(4 * 1024**3, hard)
    resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
    try:
        regressor = Path(directory) / "regressor.ckpt"
        classifier = Path(directory) / "classifier.ckpt"
        _verified_copy(config.regressor_checkpoint, regressor, config.regressor_sha256)
        _verified_copy(config.classifier_checkpoint, classifier, config.classifier_sha256)
        pair = _fit_sdk(payload, regressor, classifier)
        connection.send(("ready",))
        while True:
            command = connection.recv()
            if command == ("close",):
                break
            if not isinstance(command, tuple) or len(command) != 2 or command[0] != "predict":
                raise PredictionError("invalid_model_input")
            try:
                result = _predict_pair(pair, command[1])
                connection.send(("prediction", result.expected_sleep_minutes, result.wake_probability_60m))
            except Exception:
                connection.send(("error", "invalid_model_output"))
    except Exception:
        try:
            connection.send(("error", "model_unavailable"))
        except (OSError, EOFError):
            pass
    finally:
        connection.close()
        quiet.close()


class TabPFNModel:
    """Fitted local context. predict() does not fit, evaluate, or call providers."""

    def __init__(
        self, provenance: ModelProvenance, process: BaseProcess, connection: Connection,
        directory: tempfile.TemporaryDirectory[str], timeout: float,
    ) -> None:
        self._provenance = provenance
        self._process = process
        self._connection = connection
        self._directory = directory
        self._timeout = timeout
        self._lock = Lock()
        self._closed = False

    @property
    def provenance(self) -> ModelProvenance:
        return self._provenance

    def predict(self, inputs: ModelInput) -> NumericalPrediction:
        inputs.__post_init__()
        if inputs.baby_id != self.provenance.baby_id:
            raise PredictionError("invalid_history_scope")
        if not self._lock.acquire(blocking=False):
            raise PredictionError("model_unavailable")
        try:
            if self._closed or not self._process.is_alive():
                raise PredictionError("model_unavailable")
            self._connection.send(("predict", inputs.values))
            if not self._connection.poll(self._timeout):
                self._stop()
                raise PredictionError("model_unavailable")
            message = self._connection.recv()
            if not isinstance(message, tuple) or len(message) != 3 or message[0] != "prediction":
                raise PredictionError("invalid_model_output")
            return NumericalPrediction(message[1], message[2])
        except PredictionError:
            raise
        except Exception:
            self._stop()
            raise PredictionError("model_unavailable") from None
        finally:
            self._lock.release()

    def _stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._process.pid is not None:
                if self._process.is_alive():
                    try:
                        self._connection.send(("close",))
                    except (OSError, EOFError):
                        pass
                self._process.join(timeout=2)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=2)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(timeout=2)
                self._process.close()
        finally:
            try:
                self._connection.close()
                self._directory.cleanup()
            finally:
                _WORKER_SLOTS.release()

    def close(self) -> None:
        with self._lock:
            self._stop()


def _fit_offline(payload: TrainingPayload, config: TabPFNConfig | None) -> TabPFNModel:
    """Private fitting entry used only by the offline trainer."""

    payload.__post_init__()
    if config is None:
        raise PredictionError("model_unavailable")
    config.__post_init__()
    if not _WORKER_SLOTS.acquire(blocking=False):
        raise PredictionError("model_unavailable")
    directory: tempfile.TemporaryDirectory[str] | None = None
    model: TabPFNModel | None = None
    parent: Connection | None = None
    child: Connection | None = None
    try:
        directory = tempfile.TemporaryDirectory(prefix="booh-tabpfn-")
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_offline_worker, args=(child, config, payload, directory.name), daemon=True)
        model = TabPFNModel(payload.provenance, process, parent, directory, config.predict_timeout_seconds)
        process.start()
        child.close()
        if not parent.poll(config.fit_timeout_seconds) or parent.recv() != ("ready",):
            raise PredictionError("model_unavailable")
        return model
    except Exception:
        if child is not None:
            child.close()
        if model is not None:
            model.close()
        else:
            if parent is not None:
                parent.close()
            if directory is not None:
                directory.cleanup()
            _WORKER_SLOTS.release()
        raise PredictionError("model_unavailable") from None
