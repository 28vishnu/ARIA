from brain.core.long_text_intelligence import analyze_long_text, split_telegram_text

def test_long_text_is_lossless_and_indexed():
    source = "# Introduction\n\n" + ("Some meaningful text.\n" * 2500) + "\n## Final section\nDone."
    packet = analyze_long_text(source, segment_chars=1024)
    assert packet["complete"] is True and packet["truncated"] is False
    assert packet["character_count"] == len(source)
    assert packet["sha256"]
    assert packet["headings"] == ("# Introduction", "## Final section")
    assert "".join(s["text"] for s in packet["segments"]) == source
    assert packet["segments"][-1]["end"] == len(source)

def test_long_text_metadata_detects_code_url_and_paths():
    packet = analyze_long_text("Code:\n```python\nprint('ok')\n```\nhttps://example.com\n./main.py")
    assert packet["contains_code"] and packet["contains_urls"] and packet["contains_paths"]

def test_telegram_split_preserves_content_and_limits_parts():
    source = ("alpha beta gamma\n" * 1500)
    parts = split_telegram_text(source, limit=380)
    assert len(parts) > 1
    assert all(len(part) <= 380 for part in parts)
    assert "".join(parts) == source

def test_empty_text_is_supported():
    packet = analyze_long_text("")
    assert packet["character_count"] == 0 and packet["complete"]
    assert split_telegram_text("") == [""]
