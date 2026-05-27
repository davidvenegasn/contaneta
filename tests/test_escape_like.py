"""Tests for LIKE wildcard escaping utility."""
from services.db_utils import escape_like


class TestEscapeLike:
    """Verify escape_like handles all metacharacters."""

    def test_should_escape_percent(self):
        assert escape_like("100%") == "100\\%"

    def test_should_escape_underscore(self):
        assert escape_like("foo_bar") == "foo\\_bar"

    def test_should_escape_backslash(self):
        assert escape_like("path\\file") == "path\\\\file"

    def test_should_escape_all_combined(self):
        assert escape_like("%_\\") == "\\%\\_\\\\"

    def test_should_leave_normal_text_unchanged(self):
        assert escape_like("hello world") == "hello world"

    def test_should_handle_empty_string(self):
        assert escape_like("") == ""

    def test_should_handle_sql_injection_attempt(self):
        result = escape_like("admin%' OR 1=1 --")
        assert "\\%" in result
        # The parametrized query handles the injection; escape_like handles wildcards
        assert result == "admin\\%' OR 1=1 --"
