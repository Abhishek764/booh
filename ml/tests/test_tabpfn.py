import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ml.prediction.contracts import NumericalPrediction, PredictionError
from ml.prediction.tabpfn import (
    TabPFNConfig,
    _fit_sdk,
    _FittedPair,
    _OfflineSocket,
    _predict_pair,
    _verified_copy,
)
from ml.tests.prediction_support import AS_OF, BABY, synthetic_history
from ml.training import TabPFNTrainer, recent_chronological_split


class Array(list):
    def __init__(self, rows, shape):
        super().__init__(rows)
        self.shape = shape


def pair(*, regression=None, probabilities=None, classes=(0, 1)):
    return _FittedPair(
        SimpleNamespace(predict=lambda x: regression if regression is not None else Array([47.0], (1,))),
        SimpleNamespace(
            predict_proba=lambda x: probabilities if probabilities is not None else Array([[0.32, 0.68]], (1, 2)),
            classes_=classes,
        ),
        SimpleNamespace(asarray=lambda x, **kwargs: x),
    )


def payload():
    return recent_chronological_split(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC").payload(BABY)


def test_sdk_regression_and_classification_outputs_are_separate_and_class_order_is_respected():
    assert _predict_pair(pair(), (0.0,) * 14) == NumericalPrediction(47, 0.68)
    assert _predict_pair(pair(classes=(1, 0), probabilities=Array([[0.68, 0.32]], (1, 2))), (0.0,) * 14) == NumericalPrediction(47, 0.68)


@pytest.mark.parametrize("regression,probabilities,classes", [
    (Array([float("nan")], (1,)), None, (0, 1)),
    (Array([float("inf")], (1,)), None, (0, 1)),
    (Array([-1], (1,)), None, (0, 1)),
    (Array([10081], (1,)), None, (0, 1)),
    (Array([47, 48], (2,)), None, (0, 1)),
    (None, Array([[0.3, float("nan")]], (1, 2)), (0, 1)),
    (None, Array([[0.3, 0.8]], (1, 2)), (0, 1)),
    (None, Array([[0.3, 1.8]], (1, 2)), (0, 1)),
    (None, Array([[0.3]], (1, 1)), (0, 1)),
    (None, None, (0, 0)), (None, None, (0, 2)),
])
def test_sdk_nan_infinity_shapes_and_class_probabilities_are_rejected(regression, probabilities, classes):
    with pytest.raises(PredictionError, match="invalid_model_output"):
        _predict_pair(pair(regression=regression, probabilities=probabilities, classes=classes), (0.0,) * 14)


def test_real_sdk_api_contract_uses_cpu_local_paths_fixed_seed_and_fit_once(monkeypatch, tmp_path):
    calls = []

    class Estimator:
        @classmethod
        def create_default_for_version(cls, version, **kwargs):
            calls.append((version, kwargs))
            return cls()

        def fit(self, x, y):
            calls.append((len(x), len(y)))

    modules = {
        "numpy": SimpleNamespace(asarray=lambda x, **kwargs: x),
        "torch": SimpleNamespace(
            set_num_threads=lambda n: None, set_num_interop_threads=lambda n: None,
            manual_seed=lambda n: None, use_deterministic_algorithms=lambda enabled: None,
        ),
        "tabpfn": SimpleNamespace(TabPFNRegressor=Estimator, TabPFNClassifier=Estimator),
        "tabpfn.constants": SimpleNamespace(ModelVersion=SimpleNamespace(V2="v2")),
    }
    monkeypatch.setattr("ml.prediction.tabpfn.importlib.metadata.version", lambda package: "9.1.0")
    monkeypatch.setattr("ml.prediction.tabpfn.importlib.import_module", lambda module: modules[module])
    result = _fit_sdk(payload(), tmp_path / "regressor.ckpt", tmp_path / "classifier.ckpt")
    assert result.regressor is not result.classifier
    for version, config in calls[:2]:
        assert version == "v2"
        assert config["device"] == "cpu"
        assert config["random_state"] == 0
        assert config["n_estimators"] == 2
        assert config["ignore_pretraining_limits"] is False
        assert config["model_path"] != "auto"
    assert len(calls) == 4


def test_missing_or_unsupported_sdk_version_is_model_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("ml.prediction.tabpfn.importlib.metadata.version", lambda package: "0.0.0")
    with pytest.raises(PredictionError, match="model_unavailable"):
        _fit_sdk(payload(), tmp_path / "regressor.ckpt", tmp_path / "classifier.ckpt")


def test_unconfigured_optional_runtime_never_downloads_or_loads_weights():
    with pytest.raises(PredictionError, match="model_unavailable"):
        TabPFNTrainer().fit(payload())


def test_checksum_mismatch_rejects_before_sdk_or_weight_execution(tmp_path):
    source = tmp_path / "synthetic.ckpt"
    source.write_bytes(b"synthetic-not-a-model")
    destination = tmp_path / "copied.ckpt"
    with pytest.raises(PredictionError, match="invalid_model_configuration"):
        _verified_copy(source, destination, "0" * 64)


def test_local_hash_verified_copy_and_safe_configuration(tmp_path):
    source = tmp_path / "synthetic.ckpt"
    content = b"synthetic-not-a-model"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    copied = tmp_path / "copied.ckpt"
    _verified_copy(source, copied, digest)
    assert copied.read_bytes() == content
    config = TabPFNConfig(source, copied, digest, digest)
    for kwargs in (
        {"regressor_checkpoint": source.relative_to(tmp_path)},
        {"regressor_sha256": "missing"}, {"fit_timeout_seconds": float("inf")},
        {"predict_timeout_seconds": 60},
    ):
        with pytest.raises(PredictionError):
            replace(config, **kwargs)
    link = tmp_path / "linked.ckpt"
    link.symlink_to(source)
    with pytest.raises(PredictionError):
        replace(config, classifier_checkpoint=link)


def test_worker_missing_or_untrusted_weights_has_bounded_private_failure(tmp_path, caplog, capsys):
    source = tmp_path / "synthetic.ckpt"
    source.write_bytes(b"synthetic-not-a-model")
    config = TabPFNConfig(source, source, "0" * 64, "0" * 64, fit_timeout_seconds=5)
    with pytest.raises(PredictionError, match="model_unavailable"):
        TabPFNTrainer(config).fit(payload())
    assert "synthetic-not-a-model" not in caplog.text
    assert "synthetic-not-a-model" not in capsys.readouterr().err


def test_worker_network_socket_guard_denies_ipv4_and_ipv6():
    import socket

    for family in (socket.AF_INET, socket.AF_INET6):
        with pytest.raises(PredictionError, match="model_unavailable"):
            _OfflineSocket(family)
    with _OfflineSocket(socket.AF_UNIX):
        pass


def test_worker_timeout_terminates_process_cleans_context_and_returns_capacity(monkeypatch, tmp_path):
    from ml.prediction.tabpfn import TabPFNModel

    class Process:
        pid = 123

        def __init__(self):
            self.alive = True
            self.terminated = False

        def is_alive(self):
            return self.alive

        def join(self, **kwargs):
            pass

        def terminate(self):
            self.alive = False
            self.terminated = True

        def close(self):
            pass

    class Connection:
        def send(self, message):
            pass

        def poll(self, timeout):
            return False

        def close(self):
            pass

    releases = []
    cleanups = []
    monkeypatch.setattr("ml.prediction.tabpfn._WORKER_SLOTS", SimpleNamespace(release=lambda: releases.append(1)))
    process = Process()
    model = TabPFNModel(payload().provenance, process, Connection(), SimpleNamespace(cleanup=lambda: cleanups.append(1)), 0.1)
    split = recent_chronological_split(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    with pytest.raises(PredictionError, match="model_unavailable"):
        model.predict(split.heldout[0].inputs)
    assert process.terminated
    assert releases == cleanups == [1]
    model.close()
    assert releases == [1]


def test_worker_capacity_exhaustion_rejects_before_process_creation(monkeypatch, tmp_path):
    source = tmp_path / "synthetic.ckpt"
    source.write_bytes(b"synthetic-not-a-model")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    config = TabPFNConfig(source, source, digest, digest)
    monkeypatch.setattr("ml.prediction.tabpfn._WORKER_SLOTS", SimpleNamespace(acquire=lambda **kwargs: False))
    with pytest.raises(PredictionError, match="model_unavailable"):
        TabPFNTrainer(config).fit(payload())
