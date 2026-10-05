import ast
import logging
from pathlib import Path

import pytest

from ml.prediction.contracts import PredictionError
from ml.prediction.service import PredictionService
from ml.tests.prediction_support import AS_OF, BABY, synthetic_history
from ml.tests.test_prediction_service import StubModel, approved


def test_numeric_inference_never_fits_evaluates_or_calls_gemma(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Numerical inference must not call a trainer, evaluator, provider, or LLM")

    monkeypatch.setattr("ml.training.TabPFNTrainer.fit", forbidden)
    monkeypatch.setattr("ml.evaluation.evaluate_recent_history", forbidden)
    monkeypatch.setattr("httpx.Client.send", forbidden)
    monkeypatch.setattr("httpx.AsyncClient.send", forbidden)
    model = StubModel()
    for service in (PredictionService(), PredictionService(tabpfn_model=approved(model))):
        result = service.predict(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
        assert result.expected_sleep_minutes >= 0


def test_numeric_inference_is_silent_and_predictions_have_private_representations(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    result = PredictionService().predict(synthetic_history(), baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    with pytest.raises(PredictionError):
        PredictionService().predict([], baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    assert caplog.text == ""
    output = capsys.readouterr()
    assert output.out == output.err == ""
    assert str(BABY) not in repr(result)
    assert AS_OF.isoformat() not in repr(result.metadata)


def test_production_numeric_modules_never_import_offline_workflows_or_llm_services():
    paths = Path(__file__).parents[1] / "prediction"
    for path in paths.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(not any(part in name.lower() for part in ("gemma", "llm", "ml.training", "ml.evaluation", "fastapi", "backend")) for name in names)
