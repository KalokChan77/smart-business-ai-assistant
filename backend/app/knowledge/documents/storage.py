import asyncio
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID


class KnowledgeStorageError(Exception):
    """The private knowledge file store could not complete an operation."""


class KnowledgeStoredFileMissingError(KnowledgeStorageError):
    """The database references a private file that no longer exists."""


class KnowledgeFileStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    async def save(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        extension: str,
        content: bytes,
    ) -> str:
        key = f"{tenant_id}/{document_id}.{extension}"
        await asyncio.to_thread(self._save_sync, key, content)
        return key

    async def read(self, storage_key: str) -> bytes:
        return await asyncio.to_thread(self._read_sync, storage_key)

    async def delete(self, storage_key: str) -> None:
        await asyncio.to_thread(self._delete_sync, storage_key)

    def _save_sync(self, storage_key: str, content: bytes) -> None:
        path = self._resolve(storage_key)
        try:
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self._root, 0o700)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path.parent, 0o700)
            with NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.chmod(temporary_path, 0o600)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            os.chmod(path, 0o600)
        except OSError as exc:
            try:
                if "temporary_path" in locals():
                    temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise KnowledgeStorageError("Knowledge file could not be stored.") from exc

    def _read_sync(self, storage_key: str) -> bytes:
        path = self._resolve(storage_key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise KnowledgeStoredFileMissingError(
                "Knowledge file is missing."
            ) from exc
        except OSError as exc:
            raise KnowledgeStorageError("Knowledge file could not be read.") from exc

    def _delete_sync(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        try:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass
        except OSError as exc:
            raise KnowledgeStorageError("Knowledge file could not be deleted.") from exc

    def _resolve(self, storage_key: str) -> Path:
        relative = Path(storage_key)
        if relative.is_absolute() or ".." in relative.parts:
            raise KnowledgeStorageError("Knowledge storage key is invalid.")
        path = (self._root / relative).resolve()
        if path == self._root or self._root not in path.parents:
            raise KnowledgeStorageError("Knowledge storage key is invalid.")
        return path
