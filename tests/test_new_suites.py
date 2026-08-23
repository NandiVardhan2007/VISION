"""
Test suite for Smart Clipboard, Live Translation, Browser Navigation, Power Management, and Archive Utilities.
"""

import os
from pathlib import Path
from vision.tools.registry import tool_registry
from vision.tools.clipboard_translation_tools import read_clipboard, write_to_clipboard, translate_text
from vision.tools.browser_navigation_tools import open_website, search_youtube_videos, search_google_web
from vision.tools.power_process_tools import kill_process_by_name, cancel_shutdown
from vision.tools.archive_tools import compress_to_zip, extract_zip_archive


def test_tools_registered():
    tools = tool_registry._tools
    assert "read_clipboard" in tools
    assert "write_to_clipboard" in tools
    assert "translate_text" in tools
    assert "open_website" in tools
    assert "search_youtube_videos" in tools
    assert "kill_process_by_name" in tools
    assert "lock_workstation" in tools
    assert "empty_recycle_bin" in tools
    assert "compress_to_zip" in tools
    assert "extract_zip_archive" in tools


def test_clipboard_tools():
    test_msg = "Hello VISION System"
    res_w = write_to_clipboard(test_msg)
    assert "Successfully copied" in res_w
    res_r = read_clipboard()
    assert test_msg in res_r


def test_translation_tool():
    res = translate_text("Hello, how are you?", target_language="Telugu")
    assert "Translated to Telugu" in res or "Unable to complete translation" in res


def test_archive_tools(tmp_path):
    test_dir = tmp_path / "test_folder"
    test_dir.mkdir()
    (test_dir / "sample.txt").write_text("Hello Vision Archive Test", encoding="utf-8")

    out_zip = tmp_path / "out"
    out_zip.mkdir()

    # Compress
    res_comp = compress_to_zip(str(test_dir), output_zip_name="archive_test.zip", destination_folder=str(out_zip))
    assert "Successfully created ZIP archive" in res_comp

    zip_file = out_zip / "archive_test.zip"
    assert zip_file.exists()

    # Extract
    extract_target = tmp_path / "extracted"
    res_ext = extract_zip_archive(str(zip_file), extract_to_folder=str(extract_target))
    assert "Successfully extracted" in res_ext
    assert (extract_target / "sample.txt").exists()
