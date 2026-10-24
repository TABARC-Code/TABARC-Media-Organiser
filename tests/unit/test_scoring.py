from datetime import date


from tabarc_media.identity.parser import ParsedName, parse_filename
from tabarc_media.identity.providers import Candidate
from tabarc_media.identity.scoring import decide, normalise, score, title_similarity


def cand(title, year=None, kind="film", pid="1", original=None):
    return Candidate(provider="wikidata", provider_id=pid, title=title, year=year,
                     kind=kind, original_title=original, language="en-gb",
                     source_url=None, retrieved_on=date(2026, 10, 24), licence="CC0 1.0")


def test_normalise_folds_articles_punctuation_and_accents():
    assert normalise("The Café & Dog!") == "cafe and dog"
    assert normalise("A") == "a"  # a lone article is not stripped to nothing


def test_similarity_is_one_for_equal_normalised_titles():
    assert title_similarity("Some Film", "some film.") == 1.0
    assert title_similarity("", "x") == 0.0


def test_exact_title_and_year_is_accepted():
    d = decide(parse_filename("Some Film (2019).mkv"),
               [cand("Some Film", 2019), cand("Other Thing", 2001, pid="2")])
    assert d.status == "accept"
    assert d.best.candidate.title == "Some Film"


def test_near_tie_goes_to_review_not_accepted():
    d = decide(parse_filename("Some Film (2019).mkv"),
               [cand("Some Film", 2019), cand("Some Film", 2019, pid="2")])
    assert d.status == "review"
    assert "tie" in d.reason


def test_wrong_year_is_not_accepted():
    d = decide(parse_filename("Some Film (2019).mkv"), [cand("Some Film", 1975)])
    assert d.status != "accept"


def test_no_close_candidate_is_none():
    d = decide(parse_filename("Some Film (2019).mkv"), [cand("Completely Different", 2019)])
    assert d.status == "none"


def test_thin_names_always_go_to_review_even_with_a_perfect_hit():
    d = decide(parse_filename("Random Thing.mkv"), [cand("Random Thing")])
    assert d.status == "review"
    assert "too thin" in d.reason
    # Candidates are kept so a person can pick one.
    assert d.best is not None and d.best.candidate.title == "Random Thing"
    assert len(d.ranked) == 1


def test_multi_episode_and_empty_titles_never_accept():
    assert decide(parse_filename("Show.S01E01E02.mkv"), [cand("Show", 2000, "tv")]).status == "review"
    assert decide(ParsedName(None, None, None, None, None, True), [cand("x")]).status == "review"


def test_episode_names_prefer_tv_entries():
    p = parse_filename("Show Name S02E05.mkv")
    d = decide(p, [cand("Show Name", 2008, kind="film", pid="f"),
                   cand("Show Name", 2008, kind="tv", pid="t")])
    assert d.best.candidate.kind == "tv"


def test_expected_kinds_filters_pool():
    p = parse_filename("Some Film (2019).mkv")
    d = decide(p, [cand("Some Film", 2019, kind="book")], expected_kinds=frozenset({"film"}))
    assert d.status == "none"


def test_original_title_can_match():
    s = score(parse_filename("Amelie (2001).mkv"),
              cand("Le Fabuleux Destin d'Amélie Poulain", 2001, original="Amelie"))
    assert s.score >= 0.9


# ---- found on a real library: sources agreeing, and near-miss neighbours

def other(provider, title, year, kind="tv", pid="x"):
    c = cand(title, year, kind=kind, pid=pid)
    return Candidate(**{**c.__dict__, "provider": provider})


def test_two_sources_agreeing_is_corroboration_not_a_tie():
    p = parse_filename("Breaking Bad S01E01.mkv")
    d = decide(p, [other("tvmaze", "Breaking Bad", 2008, pid="169"),
                   other("wikidata", "Breaking Bad", 2008, pid="Q1079")])
    assert d.status == "accept"
    assert "agreed by 2 sources" in d.reason


def test_exact_title_is_not_blocked_by_a_fuzzy_neighbour():
    p = parse_filename("Breaking Bad S01E01.mkv")
    d = decide(p, [other("tvmaze", "Breaking Bad", 2008, pid="169"),
                   other("tvmaze", "Breaking Band", 2016, pid="2")])
    assert d.status == "accept"
    assert d.best.candidate.title == "Breaking Bad"


def test_same_source_listing_the_same_title_twice_is_still_a_tie():
    p = parse_filename("Home S01E01.mkv")
    d = decide(p, [other("tvmaze", "Home", 2010, pid="1"), other("tvmaze", "Home", 2010, pid="2")])
    assert d.status == "review" and "tie" in d.reason


def test_two_exact_shows_with_different_years_and_no_year_in_name_is_a_tie():
    p = parse_filename("Doctor Who S01E01.mkv")
    d = decide(p, [other("tvmaze", "Doctor Who", 1963, pid="1"),
                   other("tvmaze", "Doctor Who", 2005, pid="2")])
    assert d.status == "review"


def test_sources_that_disagree_on_year_are_not_merged():
    p = parse_filename("Some Show S01E01.mkv")
    d = decide(p, [other("tvmaze", "Some Show", 2008, pid="1"),
                   other("wikidata", "Some Show", 2015, pid="Q2")])
    assert d.status == "review"
