import pytest

from tabarc_media.identity.parser import parse_filename


@pytest.mark.parametrize(
    "name, title, year",
    [
        ("Some.Film.2019.1080p.BluRay.x264.mkv", "Some Film", 2019),
        ("Some Film (2019).mkv", "Some Film", 2019),
        ("Some_Film_2019_WEB-DL.mp4", "Some Film", 2019),
        ("1917.2019.2160p.mkv", "1917", 2019),
        ("2001 A Space Odyssey (1968).mkv", "2001 A Space Odyssey", 1968),
    ],
)
def test_films(name, title, year):
    p = parse_filename(name)
    assert p.title == title
    assert p.year == year
    assert not p.is_episode


@pytest.mark.parametrize(
    "name, title, season, episode",
    [
        ("Show.Name.S02E05.720p.HDTV.mkv", "Show Name", 2, 5),
        ("show name - s1e12 - Pilot.mkv", "show name", 1, 12),
        ("Show Name 2x05 Title.mkv", "Show Name", 2, 5),
        ("Show.Name.S02E005.mkv", "Show Name", 2, 5),
        ("Show Name Season 2 Episode 5.mkv", "Show Name", 2, 5),
        ("Show.Name.S02.E05.mkv", "Show Name", 2, 5),
    ],
)
def test_episodes(name, title, season, episode):
    p = parse_filename(name)
    assert p.title == title
    assert (p.season, p.episode) == (season, episode)
    assert p.is_episode
    assert not p.needs_review


def test_multi_episode_is_declined_not_guessed():
    p = parse_filename("Show.Name.S01E01E02.mkv")
    assert p.title is None
    assert p.unsupported == "multi-episode file"
    assert p.needs_review


def test_bare_digits_and_empty_titles_need_review():
    assert parse_filename("1234.mkv").needs_review
    assert parse_filename("[1080p].mkv").title is None
    assert parse_filename("[1080p].mkv").needs_review


def test_title_only_needs_review():
    p = parse_filename("Random Thing.mkv")
    assert p.title == "Random Thing"
    assert p.needs_review


def test_brackets_removed_from_title():
    p = parse_filename("[GroupTag] Some Film (2010) [x265].mkv")
    assert p.title == "Some Film"
    assert p.year == 2010
