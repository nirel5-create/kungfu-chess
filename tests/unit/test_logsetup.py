import logging
import os
import re

import pytest

from common.logsetup import add_file_logging, sanitize_for_filename


@pytest.fixture
def _attached_handlers():
    """Tracks handlers a test attaches to the root logger via
    add_file_logging, so the test can remove and close them afterward.
    add_file_logging touches genuinely global state (the root logger) --
    without this, a handler (and its open file) would leak into every
    later test in the same process, and on Windows a leaked open
    FileHandler also blocks tmp_path from being cleaned up."""
    handlers = []
    yield handlers
    root = logging.getLogger()
    for handler in handlers:
        root.removeHandler(handler)
        handler.close()


def _log_once(logger_name, message):
    """A throwaway logger, given its own explicit level so the message is
    never dropped by level filtering regardless of the root logger's
    ambient level in this test session -- effective level is looked up by
    walking ancestors only when the logger's OWN level is unset (NOTSET),
    so setting it here means root's level cannot suppress this call."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.info(message)


def test_creates_the_log_files_parent_directory_if_missing(tmp_path, _attached_handlers):
    log_path = tmp_path / "nested" / "server.log"
    assert not log_path.parent.exists()
    handler = add_file_logging(str(log_path))
    _attached_handlers.append(handler)
    assert log_path.parent.is_dir()


def test_creates_the_log_file_itself(tmp_path, _attached_handlers):
    log_path = tmp_path / "server.log"
    handler = add_file_logging(str(log_path))
    _attached_handlers.append(handler)
    assert log_path.is_file()


def test_does_not_raise_when_the_directory_already_exists(tmp_path, _attached_handlers):
    log_path = tmp_path / "server.log"
    os.makedirs(tmp_path, exist_ok=True)
    handler = add_file_logging(str(log_path))
    _attached_handlers.append(handler)
    assert log_path.is_file()


def test_a_logged_message_is_written_with_timestamp_level_and_message(tmp_path, _attached_handlers):
    log_path = tmp_path / "server.log"
    handler = add_file_logging(str(log_path))
    _attached_handlers.append(handler)

    _log_once("test_logsetup.timestamp_level_message", "hello world")
    handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "hello world" in content
    assert "INFO" in content
    # A timestamp starting with a four-digit year -- logging.Formatter's
    # default asctime shape, e.g. "2026-07-30 12:00:00,000".
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", content)


def test_a_logged_message_includes_the_logger_name(tmp_path, _attached_handlers):
    log_path = tmp_path / "client.log"
    handler = add_file_logging(str(log_path))
    _attached_handlers.append(handler)

    _log_once("test_logsetup.logger_name", "distinguishable message")
    handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "test_logsetup.logger_name" in content


def test_returns_the_attached_handler(tmp_path, _attached_handlers):
    log_path = tmp_path / "server.log"
    handler = add_file_logging(str(log_path))
    _attached_handlers.append(handler)
    assert isinstance(handler, logging.FileHandler)
    assert handler in logging.getLogger().handlers


def test_does_not_remove_an_existing_console_handler(tmp_path, _attached_handlers):
    root = logging.getLogger()
    console_handler = logging.StreamHandler()
    root.addHandler(console_handler)
    try:
        log_path = tmp_path / "server.log"
        handler = add_file_logging(str(log_path))
        _attached_handlers.append(handler)
        assert console_handler in root.handlers
    finally:
        root.removeHandler(console_handler)


def test_two_calls_write_to_two_independent_files(tmp_path, _attached_handlers):
    server_log = tmp_path / "server.log"
    client_log = tmp_path / "client.log"
    server_handler = add_file_logging(str(server_log))
    client_handler = add_file_logging(str(client_log))
    _attached_handlers.append(server_handler)
    _attached_handlers.append(client_handler)

    _log_once("test_logsetup.two_files", "shared format, separate files")
    server_handler.flush()
    client_handler.flush()

    # Both files get every record (both are on the root logger), but each
    # is its own file -- proof the two sides do not overwrite one another.
    assert "shared format, separate files" in server_log.read_text(encoding="utf-8")
    assert "shared format, separate files" in client_log.read_text(encoding="utf-8")


def test_sanitize_leaves_an_ordinary_username_untouched():
    assert sanitize_for_filename("alice123") == "alice123"


def test_sanitize_keeps_dashes_and_underscores():
    assert sanitize_for_filename("al-ice_99") == "al-ice_99"


def test_sanitize_replaces_a_path_separator():
    # The exact case this exists for: an unsanitized "../server" or
    # "a/b" would escape the logs/ folder entirely.
    assert sanitize_for_filename("../server") == "___server"
    assert sanitize_for_filename("a/b\\c") == "a_b_c"


def test_sanitize_replaces_characters_illegal_in_a_windows_filename():
    assert sanitize_for_filename("a:b*c?d") == "a_b_c_d"


def test_sanitize_replaces_whitespace():
    assert sanitize_for_filename("a b") == "a_b"


def test_sanitize_of_an_empty_string_is_an_empty_string():
    assert sanitize_for_filename("") == ""
