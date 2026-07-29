"""
Tests for the YouTube video-id parser -- "the part that actually
breaks" per RUNBOOK.md, since each URL shape has its own way to trip
up a naive regex once real query params show up. No fetcher yet: this
covers parse_video_id only.
"""
from src.youtube import parse_video_id


def test_parses_watch_url():
    assert parse_video_id("https://www.youtube.com/watch?v=k_S1B0mG9IM") == "k_S1B0mG9IM"


def test_parses_watch_url_without_www():
    assert parse_video_id("https://youtube.com/watch?v=abc12345678") == "abc12345678"


def test_parses_watch_url_with_trailing_query_params():
    assert parse_video_id("https://www.youtube.com/watch?v=abc12345678&t=30s") == "abc12345678"


def test_parses_watch_url_with_v_param_not_first():
    assert parse_video_id(
        "https://www.youtube.com/watch?list=PL123&v=abc12345678&index=2"
    ) == "abc12345678"


def test_parses_short_url():
    assert parse_video_id("https://youtu.be/abc12345678") == "abc12345678"


def test_parses_short_url_with_query_params():
    assert parse_video_id("https://youtu.be/abc12345678?t=30") == "abc12345678"


def test_parses_shorts_url():
    assert parse_video_id("https://www.youtube.com/shorts/abc12345678") == "abc12345678"


def test_parses_shorts_url_with_query_params():
    assert parse_video_id(
        "https://www.youtube.com/shorts/abc12345678?feature=share"
    ) == "abc12345678"


def test_non_youtube_url_returns_none():
    assert parse_video_id("https://vimeo.com/12345678") is None


def test_watch_url_missing_v_param_returns_none():
    assert parse_video_id("https://www.youtube.com/watch?list=PL123") is None


def test_empty_string_returns_none():
    assert parse_video_id("") is None


def test_none_returns_none():
    assert parse_video_id(None) is None
