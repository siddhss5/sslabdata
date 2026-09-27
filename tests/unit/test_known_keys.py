"""Each known-key list names exactly the keys its loader reads, except that
`site` is known in lab.yaml without being read.

A key a loader reads but its list lacks makes valid data warn as unknown; a
key the list names but no loader reads is accepted and silently dropped. The
loaders read keys with ``[]`` and ``.get()``, so each test hands the loader a
mapping that records every key looked up that way, and compares what was
looked up with the list.
"""

from sslabdata import config, loaders
from sslabdata.config import KNOWN_KEYS, LabDataConfig
from sslabdata.loaders import (
    COLLABORATOR_KEYS, PERSON_KEYS, PROJECT_KEYS, load_collaborators,
    load_people, load_projects,
)


class Recording(dict):
    """A mapping that records each key read from it by ``[]`` or ``get()``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read = set()

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)


def read_by(load, record, monkeypatch, tmp_path):
    """The keys ``load`` reads from ``record``, the one record in its file."""
    record = Recording(record)
    monkeypatch.setattr(loaders, "read_yaml", lambda _: ([record], []))
    path = tmp_path / "records.yaml"
    path.write_text("", encoding="utf-8")
    load(str(path), [])
    return record.read


def test_person_keys_are_the_keys_load_people_reads(monkeypatch, tmp_path):
    """A key `load_people` reads but `PERSON_KEYS` lacks warns as unknown on
    valid data; the reverse silently drops a key. The corpus writes one
    unknown key, not every key a loader reads."""
    read = read_by(load_people, {"id": "aadams", "name": "Alice Adams"},
                   monkeypatch, tmp_path)
    assert read == set(PERSON_KEYS)


def test_project_keys_are_the_keys_load_projects_reads(monkeypatch, tmp_path):
    """As for people: `PROJECT_KEYS` and `load_projects` drifting apart."""
    read = read_by(load_projects, {"id": "homebot", "title": "HomeBot"},
                   monkeypatch, tmp_path)
    assert read == set(PROJECT_KEYS)


def test_collaborator_keys_are_the_keys_load_collaborators_reads(
        monkeypatch, tmp_path):
    """As for people: `COLLABORATOR_KEYS` and `load_collaborators` drifting apart."""
    read = read_by(load_collaborators, {"name": "Priya Patel"},
                   monkeypatch, tmp_path)
    assert read == set(COLLABORATOR_KEYS)


def test_lab_yaml_keys_are_the_keys_from_yaml_reads(monkeypatch, tmp_path):
    """`site` is known without being read: renderers read it, sslabdata
    passes it by."""
    data = Recording({"bib_dir": "bib"})
    monkeypatch.setattr(config, "read_yaml", lambda _: (data, []))
    path = tmp_path / "lab.yaml"
    path.write_text("", encoding="utf-8")
    LabDataConfig.from_yaml(str(path))
    assert data.read == set(KNOWN_KEYS) - {"site"}
