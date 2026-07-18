from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from pypdf import PdfWriter

from app.knowledge.documents.validation import (
    KnowledgeFileInvalidError,
    KnowledgeFileTooLargeError,
    KnowledgeFileTypeNotSupportedError,
    KnowledgeFileValidator,
)


class TrackingUpload:
    def __init__(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes = b"",
        read_error: Exception | None = None,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self._position = 0
        self._read_error = read_error
        self.closed = False
        self.read_calls = 0

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if self._read_error is not None:
            raise self._read_error
        if self._position >= len(self._content):
            return b""
        if size is None or size < 0:
            size = len(self._content) - self._position
        chunk = self._content[self._position : self._position + size]
        self._position += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def make_pdf_bytes() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


def make_docx_bytes(text: str = "知识库文档内容") -> bytes:
    output = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(output)
    return output.getvalue()


def make_docx_with_entry(entry_name: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr(entry_name, "payload")
    return output.getvalue()


async def test_validator_accepts_utf8_txt_file() -> None:
    content = "有效文本".encode()
    upload = TrackingUpload(
        filename="guide.txt",
        content_type="text/plain; charset=utf-8",
        content=content,
    )
    validator = KnowledgeFileValidator(max_bytes=len(content) + 1)

    validated = await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert validated.extension == "txt"
    assert validated.media_type == "text/plain"
    assert validated.content == content
    assert upload.closed is True


async def test_validator_accepts_parseable_pdf_file() -> None:
    content = make_pdf_bytes()
    upload = TrackingUpload(
        filename="guide.pdf",
        content_type="application/pdf",
        content=content,
    )
    validator = KnowledgeFileValidator(max_bytes=len(content) + 1)

    validated = await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert validated.extension == "pdf"
    assert validated.media_type == "application/pdf"
    assert validated.content == content
    assert upload.closed is True


async def test_validator_accepts_parseable_docx_file() -> None:
    content = make_docx_bytes()
    upload = TrackingUpload(
        filename="guide.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=content,
    )
    validator = KnowledgeFileValidator(max_bytes=len(content) + 1)

    validated = await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert validated.extension == "docx"
    assert (
        validated.media_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert validated.content == content
    assert upload.closed is True


async def test_validator_rejects_executable_extension_before_reading_and_closes_upload() -> None:
    upload = TrackingUpload(
        filename="malware.exe",
        content_type="application/octet-stream",
        content=b"MZ payload",
    )
    validator = KnowledgeFileValidator(max_bytes=100)

    with pytest.raises(KnowledgeFileTypeNotSupportedError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.read_calls == 0
    assert upload.closed is True


async def test_validator_closes_upload_when_reading_fails() -> None:
    upload = TrackingUpload(
        filename="guide.txt",
        content_type="text/plain",
        read_error=OSError("disk read failed"),
    )
    validator = KnowledgeFileValidator(max_bytes=100)

    with pytest.raises(OSError, match="disk read failed"):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_wrong_media_type() -> None:
    upload = TrackingUpload(
        filename="guide.txt",
        content_type="application/pdf",
        content=b"valid text",
    )
    validator = KnowledgeFileValidator(max_bytes=100)

    with pytest.raises(KnowledgeFileTypeNotSupportedError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_fake_pdf_content() -> None:
    upload = TrackingUpload(
        filename="guide.pdf",
        content_type="application/pdf",
        content=b"%PDF-not really a parseable pdf",
    )
    validator = KnowledgeFileValidator(max_bytes=100)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_corrupt_docx_content() -> None:
    upload = TrackingUpload(
        filename="guide.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"not a zip",
    )
    validator = KnowledgeFileValidator(max_bytes=100)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_docx_filename_with_backslash_path() -> None:
    content = make_docx_bytes()
    upload = TrackingUpload(
        filename="dir\\guide.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=content,
    )
    validator = KnowledgeFileValidator(max_bytes=len(content) + 1)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_docx_filename_with_directory_traversal() -> None:
    content = make_docx_bytes()
    upload = TrackingUpload(
        filename="../guide.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=content,
    )
    validator = KnowledgeFileValidator(max_bytes=len(content) + 1)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_docx_archive_entry_with_backslash_path() -> None:
    content = make_docx_with_entry("word\\evil.xml")
    upload = TrackingUpload(
        filename="guide.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=content,
    )
    validator = KnowledgeFileValidator(max_bytes=len(content) + 1)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_docx_archive_entry_with_directory_traversal() -> None:
    content = make_docx_with_entry("../evil.xml")
    upload = TrackingUpload(
        filename="guide.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=content,
    )
    validator = KnowledgeFileValidator(max_bytes=len(content) + 1)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_non_utf8_txt_content() -> None:
    upload = TrackingUpload(
        filename="guide.txt",
        content_type="text/plain",
        content=b"\xff\xfe\xfd",
    )
    validator = KnowledgeFileValidator(max_bytes=100)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_empty_file() -> None:
    upload = TrackingUpload(filename="guide.txt", content_type="text/plain", content=b"")
    validator = KnowledgeFileValidator(max_bytes=1)

    with pytest.raises(KnowledgeFileInvalidError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True


async def test_validator_rejects_files_larger_than_configured_limit() -> None:
    upload = TrackingUpload(
        filename="guide.txt",
        content_type="text/plain",
        content=b"123456",
    )
    validator = KnowledgeFileValidator(max_bytes=5)

    with pytest.raises(KnowledgeFileTooLargeError):
        await validator.read_and_validate(upload)  # type: ignore[arg-type]

    assert upload.closed is True
