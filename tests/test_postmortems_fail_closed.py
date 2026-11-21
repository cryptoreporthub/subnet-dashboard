"""A corrupt postmortem file must stop a write, not get overwritten (#1578)."""

import pytest

from internal.judges import postmortems

PREDICTION = {"id": "pred-1", "netuid": 1, "direction": "up", "predicted_pct": 2.0}


@pytest.fixture
def pm_dir(tmp_path, monkeypatch):
    directory = tmp_path / "postmortems"
    directory.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(directory))
    return directory


@pytest.mark.parametrize(
    "corrupt",
    [b'[{"prediction_id": "old", "truncated', b"not json at all", b'{"a": 1}'],
    ids=["torn", "garbage", "object-root"],
)
def test_record_refuses_to_overwrite_a_corrupt_file(pm_dir, corrupt):
    target = pm_dir / "oracle.json"
    target.write_bytes(corrupt)

    with pytest.raises(postmortems.PostmortemFileCorrupt):
        postmortems.record("oracle", PREDICTION, actual_pct=-1.0)

    assert target.read_bytes() == corrupt


def test_record_still_creates_the_file_when_none_exists(pm_dir):
    postmortems.record("oracle", PREDICTION, actual_pct=-1.0)

    assert (pm_dir / "oracle.json").exists()
