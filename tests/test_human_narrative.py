"""Human-friendly narrative copy."""

from internal.council.human_narrative import (
    calibration_version_story,
    episode_kind_label,
    origin_story,
)


def test_calibration_version_story_beat():
    story = calibration_version_story("1.2", "1.3", 0.62, 0.55, True, version_bumped=True)
    assert "1.3" in story
    assert "1.2" in story
    assert "beat" in story.lower()


def test_calibration_version_story_no_bump():
    story = calibration_version_story("1.2", "1.2", 0.56, 0.55, True, version_bumped=False)
    assert "still on v1.2" in story.lower()


def test_origin_story_readable():
    story = origin_story("Dark Horse", "Martin & Shi (2024). Forecasting Crashes", "expr", 0.2)
    assert "Dark Horse" in story
    assert "Martin" in story


def test_episode_kind_labels():
    assert episode_kind_label("subnet_divergence") == "Reality check"
