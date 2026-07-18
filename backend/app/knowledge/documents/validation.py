import hashlib
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from docx import Document as load_docx
from fastapi import UploadFile
from pypdf import PdfReader

_READ_CHUNK_SIZE = 1024 * 1024
_MAX_DOCX_ENTRIES = 2000
_MAX_DOCX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_DOCX_COMPRESSION_RATIO = 100
_MAX_PDF_PAGES = 500
_ALLOWED_MEDIA_TYPES = {
    "txt": {"text/plain", "application/octet-stream"},
    "pdf": {"application/pdf", "application/octet-stream"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
}
_CANONICAL_MEDIA_TYPES = {
    "txt": "text/plain",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class KnowledgeFileValidationError(Exception):
    """Base class for safe public file validation failures."""


class KnowledgeFileTooLargeError(KnowledgeFileValidationError):
    pass


class KnowledgeFileTypeNotSupportedError(KnowledgeFileValidationError):
    pass


class KnowledgeFileInvalidError(KnowledgeFileValidationError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedKnowledgeFile:
    filename: str
    extension: str
    media_type: str
    content: bytes
    size_bytes: int
    sha256: str


class KnowledgeFileValidator:
    def __init__(self, *, max_bytes: int) -> None:
        self._max_bytes = max_bytes

    async def read_and_validate(self, upload: UploadFile) -> ValidatedKnowledgeFile:
        try:
            filename = self._validate_filename(upload.filename)
            extension = Path(filename).suffix.lstrip(".").lower()
            if extension not in _ALLOWED_MEDIA_TYPES:
                raise KnowledgeFileTypeNotSupportedError(
                    "Knowledge file extension is not supported."
                )

            media_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
            if media_type not in _ALLOWED_MEDIA_TYPES[extension]:
                raise KnowledgeFileTypeNotSupportedError(
                    "Knowledge file media type is not supported."
                )

            content = await self._read_limited(upload)
            if not content:
                raise KnowledgeFileInvalidError("Knowledge file is empty.")
            self._validate_content(extension, content)
            return ValidatedKnowledgeFile(
                filename=filename,
                extension=extension,
                media_type=_CANONICAL_MEDIA_TYPES[extension],
                content=content,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        finally:
            await upload.close()

    async def _read_limited(self, upload: UploadFile) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = await upload.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > self._max_bytes:
                raise KnowledgeFileTooLargeError(
                    "Knowledge file exceeds the configured size limit."
                )
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_filename(filename: str | None) -> str:
        if filename is None:
            raise KnowledgeFileInvalidError("Knowledge filename is required.")
        normalized = filename.strip()
        if (
            not normalized
            or len(normalized) > 200
            or normalized in {".", ".."}
            or "/" in normalized
            or "\\" in normalized
            or any(ord(character) < 32 for character in normalized)
        ):
            raise KnowledgeFileInvalidError("Knowledge filename is invalid.")
        return normalized

    def _validate_content(self, extension: str, content: bytes) -> None:
        validators = {
            "txt": self._validate_txt,
            "pdf": self._validate_pdf,
            "docx": self._validate_docx,
        }
        validators[extension](content)

    @staticmethod
    def _validate_txt(content: bytes) -> None:
        if b"\x00" in content:
            raise KnowledgeFileInvalidError("TXT file contains NUL bytes.")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise KnowledgeFileInvalidError("TXT file must use UTF-8.") from exc
        if not text.strip():
            raise KnowledgeFileInvalidError("TXT file contains no text.")

    @staticmethod
    def _validate_pdf(content: bytes) -> None:
        if not content.startswith(b"%PDF-"):
            raise KnowledgeFileInvalidError("PDF signature is invalid.")
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise KnowledgeFileInvalidError("Encrypted PDF is not supported.")
            page_count = len(reader.pages)
        except KnowledgeFileInvalidError:
            raise
        except Exception as exc:
            raise KnowledgeFileInvalidError("PDF file could not be parsed.") from exc
        if page_count < 1 or page_count > _MAX_PDF_PAGES:
            raise KnowledgeFileInvalidError("PDF page count is invalid.")

    @staticmethod
    def _validate_docx(content: bytes) -> None:
        try:
            with ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > _MAX_DOCX_ENTRIES:
                    raise KnowledgeFileInvalidError(
                        "DOCX contains too many archive entries."
                    )
                total_uncompressed = 0
                names: set[str] = set()
                for entry in entries:
                    if "\\" in entry.filename:
                        raise KnowledgeFileInvalidError(
                            "DOCX archive path is invalid."
                        )
                    path = PurePosixPath(entry.filename)
                    if path.is_absolute() or ".." in path.parts:
                        raise KnowledgeFileInvalidError(
                            "DOCX archive path is invalid."
                        )
                    if entry.flag_bits & 0x1:
                        raise KnowledgeFileInvalidError(
                            "Encrypted DOCX is not supported."
                        )
                    names.add(entry.filename)
                    total_uncompressed += entry.file_size
                    if total_uncompressed > _MAX_DOCX_UNCOMPRESSED_BYTES:
                        raise KnowledgeFileInvalidError(
                            "DOCX uncompressed content is too large."
                        )
                if (
                    total_uncompressed > max(len(content), 1)
                    * _MAX_DOCX_COMPRESSION_RATIO
                ):
                    raise KnowledgeFileInvalidError(
                        "DOCX compression ratio is unsafe."
                    )
                required = {"[Content_Types].xml", "word/document.xml"}
                if not required.issubset(names):
                    raise KnowledgeFileInvalidError("DOCX structure is invalid.")
        except KnowledgeFileInvalidError:
            raise
        except BadZipFile as exc:
            raise KnowledgeFileInvalidError("DOCX ZIP structure is invalid.") from exc
        except Exception as exc:
            raise KnowledgeFileInvalidError("DOCX file could not be inspected.") from exc

        try:
            document = load_docx(BytesIO(content))
            text_parts = [paragraph.text for paragraph in document.paragraphs]
            text_parts.extend(
                cell.text
                for table in document.tables
                for row in table.rows
                for cell in row.cells
            )
        except Exception as exc:
            raise KnowledgeFileInvalidError("DOCX file could not be parsed.") from exc
        if not any(re.search(r"\S", value) for value in text_parts):
            raise KnowledgeFileInvalidError("DOCX contains no text.")
