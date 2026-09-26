"""
Export utilities for sslabdata.

Serializes LabData to YAML or JSON files.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa <siddh@cs.washington.edu>
MIT License - see LICENSE file for details.
"""

import json
import os
import stat
import uuid
import yaml
from pathlib import Path

from .models import LabData


def _write(output_path: str, text: str) -> None:
    """Write a serialized document, after it has been serialized.

    The document is built in full before anything is created, so a document
    sslabdata refuses to emit -- one whose `source.file` is absolute, say --
    leaves no file behind. It is then written in full to a temporary sibling
    and moved over the destination in one step, so a failure at any point
    leaves an existing file as it was, creates none where there was none, and
    leaves no temporary file behind.
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    # The temporary file is never more permissive than the file it replaces,
    # and its name does not depend on the destination's, which may already be
    # as long as a name can be.
    try:
        mode = stat.S_IMODE(output_file.stat().st_mode)
    except FileNotFoundError:
        mode = None
    temp = output_file.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o666 if mode is None else mode)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            if mode is not None:
                os.chmod(temp, mode)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, output_file)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def export_to_yaml(data: LabData, output_path: str):
    """Export LabData to a YAML file.

    Args:
        data: Assembled LabData instance
        output_path: Path to output YAML file
    """
    _write(output_path,
           yaml.dump(data.to_dict(), default_flow_style=False,
                     allow_unicode=True, sort_keys=False))


def export_to_json(data: LabData, output_path: str, indent: int = 2):
    """Export LabData to a JSON file.

    Args:
        data: Assembled LabData instance
        output_path: Path to output JSON file
        indent: Indentation level for pretty printing
    """
    _write(output_path,
           json.dumps(data.to_dict(), indent=indent, ensure_ascii=False))
