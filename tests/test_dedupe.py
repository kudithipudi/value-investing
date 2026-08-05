from app.services.dedupe import dedupe_new_ideas, fragment_key, normalize_author


def test_normalize_author_strips_parenthetical_and_case():
    assert normalize_author("Dennis Zhuo ('26)") == "dennis zhuo"
    assert normalize_author("Dennis Zhuo") == "dennis zhuo"
    assert normalize_author("null") is None
    assert normalize_author(None) is None
    assert normalize_author("") is None


def test_fragment_key_requires_author():
    assert fragment_key(
        issue_id=1, kind="pitch", ticker="AAPL", company="Apple", direction="long", author=None
    ) is None


def test_fragment_key_treats_literal_null_ticker_as_missing():
    """The LLM sometimes emits the literal string "null" instead of JSON null;
    two different companies must not collapse into one "NULL" ticker bucket."""
    key1 = fragment_key(
        issue_id=1, kind="position", ticker="null", company="Bank Rakyat",
        direction="long", author="Jane Investor",
    )
    key2 = fragment_key(
        issue_id=1, kind="position", ticker="null", company="Royal Vopak",
        direction="long", author="Jane Investor",
    )
    assert key1 is not None and key2 is not None
    assert key1 != key2


def test_fragment_key_matches_same_pitch_fragments():
    common = dict(issue_id=7, kind="position", ticker="TREX", company="Trex Company",
                  direction="long", author="Gavin Baker, Atreides Management")
    assert fragment_key(**common) == fragment_key(**{**common, "company": "Trex Co."})


def test_fragment_key_keeps_different_directions_separate():
    common = dict(issue_id=7, kind="pitch", ticker="TREX", company="Trex Company", author="Gavin Baker")
    long_key = fragment_key(**common, direction="long")
    short_key = fragment_key(**common, direction="short")
    assert long_key != short_key


def test_dedupe_new_ideas_merges_fragments_keeps_longest_thesis():
    ideas = [
        {"ticker": "UBER", "company": "Uber", "kind": "pitch", "direction": "long",
         "author": "Dennis Zhuo ('26)", "thesis": "short fragment"},
        {"ticker": "UBER", "company": "Uber", "kind": "pitch", "direction": "long",
         "author": "Dennis Zhuo", "thesis": "a much longer and more complete fragment of the same pitch"},
    ]
    result = dedupe_new_ideas(ideas)
    assert len(result) == 1
    assert result[0]["thesis"] == "a much longer and more complete fragment of the same pitch"


def test_dedupe_new_ideas_leaves_distinct_mentions_alone():
    ideas = [
        {"ticker": None, "company": "Bank Rakyat", "kind": "position", "direction": "long",
         "author": "William von Mueffling", "thesis": "one"},
        {"ticker": None, "company": "Royal Vopak", "kind": "position", "direction": "long",
         "author": "William von Mueffling", "thesis": "two"},
    ]
    result = dedupe_new_ideas(ideas)
    assert len(result) == 2


def test_dedupe_new_ideas_passes_through_ideas_with_no_author():
    ideas = [
        {"ticker": "AAPL", "company": "Apple", "kind": "pitch", "direction": "long",
         "author": None, "thesis": "one"},
        {"ticker": "AAPL", "company": "Apple", "kind": "pitch", "direction": "long",
         "author": None, "thesis": "two"},
    ]
    result = dedupe_new_ideas(ideas)
    assert len(result) == 2
