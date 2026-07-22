import os
import stat
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.knowledge.documents.storage import (
    KnowledgeFileStorage,
    KnowledgeStorageError,
    KnowledgeStoredFileMissingError,
)


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def test_storage_saves_files_under_uuid_key(tmp_path: Path) -> None:
    storage = KnowledgeFileStorage(tmp_path / "knowledge")
    tenant_id = uuid4()
    document_id = uuid4()

    key = await storage.save(
        tenant_id=tenant_id,
        document_id=document_id,
        extension="txt",
        content=b"content",
    )

    tenant_part, filename = key.split("/", 1)
    stored_document_id, extension = filename.rsplit(".", 1)
    assert UUID(tenant_part) == tenant_id
    assert UUID(stored_document_id) == document_id
    assert extension == "txt"


async def test_storage_creates_private_root_tenant_and_file_modes(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    storage = KnowledgeFileStorage(root)
    tenant_id = uuid4()
    document_id = uuid4()

    key = await storage.save(
        tenant_id=tenant_id,
        document_id=document_id,
        extension="pdf",
        content=b"%PDF content",
    )

    if os.name == "nt":
        # Windows exposes inherited NTFS ACLs rather than POSIX permission bits.
        assert root.is_dir()
        assert (root / str(tenant_id)).is_dir()
        assert (root / key).is_file()
    else:
        assert file_mode(root) == 0o700
        assert file_mode(root / str(tenant_id)) == 0o700
        assert file_mode(root / key) == 0o600


async def test_storage_atomically_overwrites_existing_file_content(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    storage = KnowledgeFileStorage(root)
    tenant_id = uuid4()
    document_id = uuid4()

    key = await storage.save(
        tenant_id=tenant_id,
        document_id=document_id,
        extension="txt",
        content=b"old content",
    )
    same_key = await storage.save(
        tenant_id=tenant_id,
        document_id=document_id,
        extension="txt",
        content=b"new content",
    )

    assert same_key == key
    assert await storage.read(key) == b"new content"
    assert list((root / str(tenant_id)).glob(f".{document_id}.txt.*")) == []
    if os.name != "nt":
        assert file_mode(root / key) == 0o600


async def test_storage_reads_saved_file_content(tmp_path: Path) -> None:
    storage = KnowledgeFileStorage(tmp_path / "knowledge")
    key = await storage.save(
        tenant_id=uuid4(),
        document_id=uuid4(),
        extension="txt",
        content=b"read me",
    )

    content = await storage.read(key)

    assert content == b"read me"


async def test_storage_deletes_saved_file_and_empty_tenant_directory(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    storage = KnowledgeFileStorage(root)
    tenant_id = uuid4()
    key = await storage.save(
        tenant_id=tenant_id,
        document_id=uuid4(),
        extension="txt",
        content=b"delete me",
    )

    await storage.delete(key)

    assert not (root / key).exists()
    assert not (root / str(tenant_id)).exists()


async def test_storage_reports_missing_file_when_read_target_is_absent(tmp_path: Path) -> None:
    storage = KnowledgeFileStorage(tmp_path / "knowledge")
    missing_key = f"{uuid4()}/{uuid4()}.txt"

    with pytest.raises(KnowledgeStoredFileMissingError):
        await storage.read(missing_key)


@pytest.mark.parametrize(
    "storage_key",
    ["../outside.txt", f"{uuid4()}/../outside.txt", "/tmp/outside.txt"],
)
async def test_storage_rejects_path_traversal_keys(
    tmp_path: Path,
    storage_key: str,
) -> None:
    storage = KnowledgeFileStorage(tmp_path / "knowledge")

    with pytest.raises(KnowledgeStorageError):
        await storage.read(storage_key)


async def test_storage_rejects_save_extension_that_traverses_outside_root(tmp_path: Path) -> None:
    storage = KnowledgeFileStorage(tmp_path / "knowledge")

    with pytest.raises(KnowledgeStorageError):
        await storage.save(
            tenant_id=uuid4(),
            document_id=uuid4(),
            extension="../../outside",
            content=b"escape",
        )
