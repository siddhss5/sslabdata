"""Tests for the new LabDataConfig."""

import sslabdata
import pytest
import yaml
import tempfile
from pathlib import Path, PureWindowsPath

from sslabdata import (
    BibFile, ConfigurationError, LabData, LabDataConfig, Work, assemble,
    export_to_json,
)


def is_absolute(name):
    """Rooted under either flavour. Restated rather than imported: outside
    tests/unit/ the suite uses only sslabdata's public names."""
    return name.startswith(("/", "\\")) or PureWindowsPath(name).is_absolute()


def test_configuration_error_is_its_own_type_under_value_error():
    """SPEC.md section 1: a caller can tell a rejected configuration apart.

    It subclasses `ValueError`, so code that caught one still catches this;
    it is *not* `ValueError`, so code that wants only this does not also
    catch a `year` that is not a number, which is a different failure with a
    different owner. Asserting the exception type alone would not notice the
    second half: aliasing the name to `ValueError` keeps every
    `type(e) is ConfigurationError` assertion true.
    """
    assert issubclass(ConfigurationError, ValueError)
    assert ConfigurationError is not ValueError
    assert "ConfigurationError" in sslabdata.__all__


class TestBibFileNameIsNeverAbsolute:
    """`bib_files[].name` is emitted as `work.source.file`, which SPEC.md
    section 5 promises is never an absolute path.

    The guarantee is kept by rejecting the input rather than by rewriting it:
    rewriting would quietly drop a relative directory the user meant. Checked
    through `from_yaml()` rather than against the predicate behind it, because
    outside `tests/unit/` the suite uses only sslabdata's public names.
    """

    # Both path flavours, so the same configuration is accepted or rejected
    # wherever it is compiled -- a document is shared, and one carrying a
    # compiling machine's directory layout leaks it to every consumer.
    ABSOLUTE = ["/data/journal.bib", "//srv/journal.bib",
                "C:\\data\\journal.bib", "C:/data/journal.bib",
                "\\\\server\\share\\journal.bib", "\\journal.bib"]
    RELATIVE = ["journal.bib", "sub/journal.bib", "sub\\journal.bib",
                "./journal.bib"]

    # The code, restated here rather than imported: it is a published,
    # permanent interface (SPEC.md, "Diagnostic codes"), so a test may depend
    # on it without depending on the wording around it.
    CODE = "CONFIG-BIB-FILE-ABSOLUTE"

    def write(self, tmp_path, name):
        config_path = tmp_path / "lab.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"bib_dir": ".",
                            "bib_files": [{"name": name,
                                           "category": "Journal Papers"}]}, f)
        return config_path

    @pytest.mark.parametrize("name", ABSOLUTE)
    def test_an_absolute_name_is_rejected_at_load(self, tmp_path, name):
        config_path = self.write(tmp_path, name)
        with pytest.raises(ConfigurationError) as raised:
            LabDataConfig.from_yaml(str(config_path))
        assert type(raised.value) is ConfigurationError, type(raised.value)
        message = str(raised.value)
        assert message.startswith(self.CODE), message
        # It locates itself the way every coded diagnostic does, and names
        # the value it objected to.
        assert f"{config_path}:bib_files:name" in message
        assert name in message

    @pytest.mark.parametrize("name", RELATIVE)
    def test_a_relative_name_still_loads(self, tmp_path, name):
        config = LabDataConfig.from_yaml(str(self.write(tmp_path, name)))
        # Passed through as written: the relative directory is the user's.
        assert config.bib_files[0].name == name

    @pytest.mark.parametrize("name", ABSOLUTE)
    def test_an_absolute_name_is_rejected_when_built_by_hand(self, name):
        """`BibFile` and `LabDataConfig` are public, so a caller can assemble
        a configuration without going near YAML.

        The constructor catches the mistake where it is made, which is the
        earliest and clearest place to report it. It is not what makes the
        guarantee true -- `Work.to_dict()` is, at the boundary every emitted
        document passes through -- because this class is mutable and a name
        can be set after it was checked.
        """
        with pytest.raises(ConfigurationError) as raised:
            BibFile(name=name, category="Journal Papers")
        assert type(raised.value) is ConfigurationError, type(raised.value)
        message = str(raised.value)
        assert message.startswith(self.CODE), message
        assert "bib_files:name" in message
        assert name in message

    @pytest.mark.parametrize("name", RELATIVE)
    def test_a_relative_name_is_built_by_hand_unchanged(self, name):
        assert BibFile(name=name, category="Journal Papers").name == name

    @pytest.mark.parametrize("name", ABSOLUTE)
    def test_an_absolute_name_set_after_construction_is_rejected(self, tmp_path, name):
        """`BibFile` is a plain, mutable dataclass, which is public API.

        Checking only in the constructor leaves it one assignment away from
        being missed, so `assemble()` checks every configured name before it
        parses anything -- which fails before the work of reading the files,
        and is what this asserts. The check that *holds* is neither of them:
        it is `Work.to_dict()`, and
        `test_a_work_built_by_hand_is_rejected_when_it_is_serialized` covers
        it.
        """
        bib_file = BibFile(name="journal.bib", category="Journal Papers")
        bib_file.name = name
        with pytest.raises(ConfigurationError) as raised:
            assemble(LabDataConfig(bib_dir=str(tmp_path), bib_files=[bib_file]))
        assert type(raised.value) is ConfigurationError, type(raised.value)
        message = str(raised.value)
        assert message.startswith(self.CODE), message
        assert name in message

    @pytest.mark.parametrize("name", ABSOLUTE)
    def test_a_work_built_by_hand_is_rejected_when_it_is_serialized(self, tmp_path,
                                                                    name):
        """The boundary every emitted document passes through.

        `Work` is public and takes `source_file` directly, so a document can
        be assembled without going near a configuration at all. Checking only
        where the name was configured leaves the guarantee to whichever entry
        point a caller happened to use; checking where the document is built
        makes it a property of the document.
        """
        work = Work(bib_id="a2024", title="A Title", authors=[], year=2024,
                    category="Journal Papers", entry_type="article",
                    source_file=name)
        with pytest.raises(ConfigurationError) as raised:
            export_to_json(LabData(works=[work]), str(tmp_path / "lab.json"))
        assert type(raised.value) is ConfigurationError, type(raised.value)
        assert str(raised.value).startswith(self.CODE)
        assert name in str(raised.value)
        assert not (tmp_path / "lab.json").exists()

    @pytest.mark.parametrize("name", RELATIVE)
    def test_a_relative_source_file_serializes_unchanged(self, name):
        """A relative directory is a name under `bib_dir`, not a path out of
        it, so the check must not reject one."""
        work = Work(bib_id="a2024", title="A Title", authors=[], year=2024,
                    category="Journal Papers", entry_type="article",
                    source_file=name)
        assert work.to_dict()["source"] == {"file": name, "key": "a2024"}

    def test_a_work_with_no_source_file_serializes(self):
        """The dataclass default is the empty string, which is not absolute."""
        work = Work(bib_id="a2024", title="A Title", authors=[], year=2024,
                    category="Journal Papers", entry_type="article")
        assert work.to_dict()["source"] == {"file": "", "key": "a2024"}

    def test_a_document_built_by_hand_never_carries_an_absolute_source(self, tmp_path):
        """End to end through the public API, with no YAML anywhere."""
        (tmp_path / "journal.bib").write_text(
            "@article{a2024,\n  title   = {A Title},\n"
            "  author  = {Adams, Alice},\n  journal = {J},\n  year    = {2024}\n}\n",
            encoding="utf-8")
        config = LabDataConfig(
            bib_dir=str(tmp_path),
            bib_files=[BibFile(name="journal.bib", category="Journal Papers")])
        document = assemble(config).to_dict()
        assert document["works"][0]["source"]["file"] == "journal.bib"
        assert not is_absolute(document["works"][0]["source"]["file"])


class TestConfigurationShape:
    """A lab.yaml of the wrong shape is rejected at load, with one coded line.

    The invalid corpus owns each configuration key; this owns what it does not
    write: the YAML value types (an empty file, a boolean, a float, a mapping, a
    set), any of which a type check keyed on the wrong Python type would let
    through or crash on."""

    def load(self, tmp_path, text):
        path = tmp_path / "lab.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ConfigurationError) as caught:
            LabDataConfig.from_yaml(str(path))
        return str(caught.value).replace(str(path), "lab.yaml")

    @pytest.mark.parametrize("text, expected", [
        ("", "CONFIG-NOT-A-MAPPING lab.yaml:::"),
        ("bib_dir: 3\n", "CONFIG-TYPE-INVALID lab.yaml:bib_dir::"),
        ("bib_dir: .\nlab: true\n", "CONFIG-TYPE-INVALID lab.yaml:lab::"),
        ("bib_dir: .\nprojects_file: 1.5\n", "CONFIG-TYPE-INVALID lab.yaml:projects_file::"),
        ("bib_dir: .\npeople_file: {a: b}\n", "CONFIG-TYPE-INVALID lab.yaml:people_file::"),
        ("bib_dir: !!set {a}\n", "CONFIG-TYPE-INVALID lab.yaml:bib_dir::"),
    ])
    def test_rejected(self, tmp_path, text, expected):
        assert self.load(tmp_path, text).startswith(expected)

    def test_unknown_keys_are_kept_for_the_assembler(self, tmp_path):
        path = tmp_path / "lab.yaml"
        path.write_text("bib_dir: .\nsite: {url: x}\npeople_fil: p.yaml\nextra: 1\n",
                        encoding="utf-8")
        config = LabDataConfig.from_yaml(str(path))
        assert config.unknown_keys == ["people_fil", "extra"]
        assert config.bib_files == []
