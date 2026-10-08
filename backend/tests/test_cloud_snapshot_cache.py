import base64
import hashlib
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from lakshya.cloud import store


class SnapshotDatabase:
    def __init__(self, identity):
        self.identity = identity
        self.rows = []
        self.blob_reads = 0
        self.metadata_reads = 0

    def set_file(self, filename, contents):
        self.rows = [
            {
                "path": filename,
                "digest": hashlib.sha256(contents).hexdigest(),
                "contents": store.encrypt(contents, f"{self.identity}/{filename}".encode()),
                "mtime": 1000000,
            }
        ]

    def execute(self, query, params):
        assert params[0] == self.identity
        if "contents" in query:
            self.blob_reads += 1
            return [row for row in self.rows if row["path"] in params[1]]
        self.metadata_reads += 1
        return [
            {key: value for key, value in row.items() if key != "contents"} for row in self.rows
        ]

    def commit(self):
        pass


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LAKSHYA_STORAGE_KEY",
        base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode(),
    )
    identity = str(uuid4())
    db = SnapshotDatabase(identity)
    return store.Workspace(identity, tmp_path / identity, db), db


def test_warm_restore_checks_metadata_without_redownloading_and_discards_dirty_disk(workspace):
    state, db = workspace
    db.set_file("profile.txt", b"committed evidence")
    state.restore()
    (state.root / "profile.txt").write_bytes(b"unsaved local changes")
    (state.root / "workspace.sqlite3-wal").write_bytes(b"uncommitted WAL")
    state.restore()
    assert (state.root / "profile.txt").read_bytes() == b"committed evidence"
    assert not (state.root / "workspace.sqlite3-wal").exists()
    assert db.metadata_reads == 2
    assert db.blob_reads == 1
    assert b"committed evidence" not in next(state.cache.iterdir()).read_bytes()


def test_changed_remote_digest_downloads_new_snapshot_and_prunes_old_cache(workspace):
    state, db = workspace
    db.set_file("profile.txt", b"first")
    state.restore()
    db.set_file("profile.txt", b"changed by another worker")
    state.restore()
    assert (state.root / "profile.txt").read_bytes() == b"changed by another worker"
    assert db.blob_reads == 2
    assert len(list(state.cache.iterdir())) == 1


@pytest.mark.parametrize("damage", ["corrupt_ciphertext", "valid_ciphertext_wrong_contents"])
def test_damaged_cache_is_replaced_from_authoritative_database(workspace, damage):
    state, db = workspace
    db.set_file("profile.txt", b"real evidence")
    state.restore()
    cache = next(state.cache.iterdir())
    cache.write_bytes(
        b"invalid"
        if damage == "corrupt_ciphertext"
        else store.encrypt(b"wrong evidence", f"{state.identity}/profile.txt".encode())
    )
    state.restore()
    assert (state.root / "profile.txt").read_bytes() == b"real evidence"
    assert db.blob_reads == 2


def test_remote_delete_removes_local_file_and_cache(workspace):
    state, db = workspace
    db.set_file("profile.txt", b"deleted remotely")
    state.restore()
    db.rows = []
    state.restore()
    assert not list(state.root.iterdir())
    assert not list(state.cache.iterdir())


def test_path_traversal_is_rejected_before_writing_files(workspace):
    state, db = workspace
    db.set_file("../escape.txt", b"bad path")
    with pytest.raises(ValueError, match="Invalid stored file path"):
        state.restore()
    assert not (state.root.parent / "escape.txt").exists()
