import ast
import logging
from pathlib import Path

import pytest

from ml.features import FeatureValidationError
from ml.tests.test_features import AS_OF, BABY, build, event


def test_histories_are_not_logged_printed_retained_or_shared_across_calls(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    feed = event("feed", 10)
    vector = build([feed])
    with pytest.raises(FeatureValidationError):
        build([event("synthetic-private-malformed-type", 10)])
    assert caplog.text == ""
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    for value in (feed, vector, vector.metadata):
        assert str(BABY) not in repr(value)
        assert AS_OF.isoformat() not in repr(value)


def test_feature_service_is_stateless_across_independent_baby_histories():
    from uuid import uuid4

    from ml.features import FeatureService

    service = FeatureService()
    first = service.build([event("feed", 10)], baby_id=BABY, as_of=AS_OF, timezone_name="UTC")
    other = uuid4()
    second = service.build([event("sleep", 60, duration=1800, baby_id=other)], baby_id=other, as_of=AS_OF, timezone_name="UTC")
    assert first.as_dict()["minutes_since_last_feed"] == 10.0
    assert second.as_dict()["minutes_since_last_feed"] == -1.0
    assert vars(service) == {}


def test_feature_package_imports_only_standard_library_modules():
    import sys

    directory = Path(__file__).parents[1]
    for path in directory.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(name.split(".")[0] in sys.stdlib_module_names for name in names)
