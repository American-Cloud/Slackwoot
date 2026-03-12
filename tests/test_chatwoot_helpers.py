"""
Unit tests for pure helper functions in app/routes/chatwoot.py

These functions have no DB or network dependencies — fast, isolated tests.
"""

import os
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production-1234")

from app.routes.chatwoot import (
    _strip_html,
    format_attachments_text,
    _is_previewable_image,
    status_emoji_text,
    register_our_message,
    _our_message_ids,
)


class TestStripHtml:
    def test_strips_paragraph_tags(self):
        assert _strip_html("<p>Hello world</p>") == "Hello world"

    def test_strips_nested_tags(self):
        assert _strip_html("<p><strong>Bold</strong> text</p>") == "Bold text"

    def test_plain_text_unchanged(self):
        assert _strip_html("plain text") == "plain text"

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_none_returns_empty(self):
        assert _strip_html(None) == ""

    def test_strips_links(self):
        result = _strip_html('<a href="http://example.com">click here</a>')
        assert result == "click here"

    def test_trims_whitespace(self):
        assert _strip_html("  <p>  hello  </p>  ") == "hello"


class TestIsPreviewableImage:
    def test_file_type_image(self):
        assert _is_previewable_image({"file_type": "image"}) is True

    def test_jpeg_extension(self):
        assert _is_previewable_image({"file_type": "jpg", "file_name": "photo.jpg"}) is True

    def test_png_extension(self):
        assert _is_previewable_image({"file_name": "screenshot.png"}) is True

    def test_gif_extension(self):
        assert _is_previewable_image({"file_name": "anim.gif"}) is True

    def test_webp_extension(self):
        assert _is_previewable_image({"file_name": "modern.webp"}) is True

    def test_svg_not_previewable(self):
        # SVG is intentionally excluded per code comment
        assert _is_previewable_image({"file_name": "icon.svg"}) is False

    def test_pdf_not_previewable(self):
        assert _is_previewable_image({"file_name": "doc.pdf", "file_type": "pdf"}) is False

    def test_mime_type_image_jpeg(self):
        assert _is_previewable_image({"file_type": "image/jpeg"}) is True

    def test_empty_attachment(self):
        assert _is_previewable_image({}) is False


class TestFormatAttachmentsText:
    def test_empty_list(self):
        assert format_attachments_text([]) == ""

    def test_single_file_attachment(self):
        att = [{"file_name": "doc.pdf", "file_type": "pdf", "file_size": 2048, "data_url": "http://example.com/doc.pdf"}]
        result = format_attachments_text(att)
        assert "doc.pdf" in result
        assert "pdf" in result
        assert "http://example.com/doc.pdf" in result
        assert "📎" in result

    def test_image_attachments_skipped(self):
        # Previewable images should NOT appear in text (they're uploaded directly)
        att = [{"file_type": "image", "file_name": "photo.jpg", "data_url": "http://example.com/photo.jpg"}]
        result = format_attachments_text(att)
        assert result == ""

    def test_multiple_non_image_attachments(self):
        atts = [
            {"file_name": "a.pdf", "file_type": "pdf", "data_url": "http://x.com/a.pdf"},
            {"file_name": "b.zip", "file_type": "zip", "data_url": "http://x.com/b.zip"},
        ]
        result = format_attachments_text(atts)
        assert "a.pdf" in result
        assert "b.zip" in result

    def test_attachment_without_url(self):
        att = [{"file_name": "doc.pdf", "file_type": "pdf", "file_size": 0}]
        result = format_attachments_text(att)
        assert "doc.pdf" in result
        # No URL means no hyperlink format
        assert "<" not in result

    def test_file_size_display(self):
        att = [{"file_name": "big.pdf", "file_type": "pdf", "file_size": 102400, "data_url": "http://x.com/big.pdf"}]
        result = format_attachments_text(att)
        assert "100.0 KB" in result


class TestStatusEmojiText:
    def test_resolved(self):
        result = status_emoji_text("resolved", {"assignee": {"name": "Alice"}})
        assert "✅" in result
        assert "Alice" in result
        assert "resolved" in result.lower()

    def test_open_reopened(self):
        result = status_emoji_text("open", {})
        assert "🔄" in result
        assert "reopen" in result.lower()

    def test_pending(self):
        result = status_emoji_text("pending", {})
        assert "⏳" in result
        assert "pending" in result.lower()

    def test_unknown_status(self):
        result = status_emoji_text("snoozed", {})
        assert "snoozed" in result

    def test_resolved_no_assignee(self):
        # Should fall back to "Agent" when no assignee provided
        result = status_emoji_text("resolved", {})
        assert "Agent" in result


class TestLoopPrevention:
    def test_register_our_message(self):
        _our_message_ids.clear()
        register_our_message(12345)
        assert 12345 in _our_message_ids

    def test_deque_max_size(self):
        _our_message_ids.clear()
        for i in range(600):
            register_our_message(i)
        # maxlen=500, so early IDs should be gone
        assert 0 not in _our_message_ids
        assert 599 in _our_message_ids
