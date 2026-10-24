import pytest

from tabarc_media.identity.parser import parse_filename, parse_path


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



def test_path_uses_folder_when_film_filename_is_thin():
    p = parse_path("Some Film (2019)/movie.mkv")
    assert (p.title, p.year) == ("Some Film", 2019)
    assert not p.needs_review


def test_path_keeps_a_filename_that_already_says_enough():
    p = parse_path("Films/Some Film (2019)/Other.Name.2001.1080p.mkv")
    assert (p.title, p.year) == ("Other Name", 2001)


def test_path_takes_show_from_nearest_non_season_folder():
    p = parse_path("Show Name (2008)/Season 2/S02E05.mkv")
    assert (p.title, p.year, p.season, p.episode) == ("Show Name", 2008, 2, 5)
    assert not p.needs_review


def test_path_with_only_season_folders_stays_unnamed():
    p = parse_path("Season 2/S02E05.mkv")
    assert p.title is None and p.needs_review


def test_path_thin_name_in_plain_folder_still_needs_review():
    assert parse_path("Films/movie.mkv").needs_review


def test_path_does_not_override_multi_episode_refusal():
    assert parse_path("Show/Season 1/Show.S01E01E02.mkv").unsupported == "multi-episode file"


def test_path_accepts_windows_separators():
    p = parse_path("Some Film (2019)\\movie.mkv")
    assert (p.title, p.year) == ("Some Film", 2019)


# ---- found on a real library: a title that contains a year-looking number

def test_bracketed_year_beats_a_number_in_the_title():
    p = parse_filename("Blade Runner 2049 (2017).mkv")
    assert (p.title, p.year) == ("Blade Runner 2049", 2017)


def test_future_looking_number_is_never_a_year():
    p = parse_filename("Blade.Runner.2049.mkv")
    assert p.year is None and p.title == "Blade Runner 2049"
    assert p.needs_review  # no year and no episode, so too thin to trust alone


def test_last_year_wins_when_title_holds_one_and_none_is_bracketed():
    p = parse_filename("Wonder.Woman.1984.2020.1080p.mkv")
    assert (p.title, p.year) == ("Wonder Woman 1984", 2020)


def test_year_one_ahead_is_still_allowed():
    from datetime import date
    nxt = date.today().year + 1
    assert parse_filename(f"Upcoming Film ({nxt}).mkv").year == nxt
    assert parse_filename(f"Upcoming Film ({nxt + 1}).mkv").year is None
