"""Smoke test: the package's public names import.

A name dropped from `sslabdata` breaks every consumer that imports it, and
no conformance test imports all of them."""


def test_core_classes_importable():
    """Verify core classes are importable from the package."""
    from sslabdata import (
        LabDataConfig,
        BibFile,
        LabData,
        Work,
        Author,
        Contributor,
        Venue,
        Link,
        Person,
        Project,
        Collaborator,
        assemble,
        export_to_yaml,
        export_to_json,
    )

