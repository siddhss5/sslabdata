"""
sslabdata - Renderer-agnostic academic lab data assembler.

Transforms BibTeX files and YAML configuration into structured data
(YAML/JSON) for academic lab websites. Framework-agnostic: works with
any static site generator, web framework, or other consumer.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

from .config import ConfigurationError, LabDataConfig, BibFile
from .models import (
    LabData, Work, Award, Author, Contributor, Venue, Link, Person, Project,
    Collaborator,
)
from .assembler import assemble, AssemblyError, AssemblyResult
from .exporters import export_to_yaml, export_to_json

__all__ = [
    "LabDataConfig",
    "BibFile",
    "ConfigurationError",
    "LabData",
    "Work",
    "Award",
    "Author",
    "Contributor",
    "Venue",
    "Link",
    "Person",
    "Project",
    "Collaborator",
    "assemble",
    "AssemblyResult",
    "AssemblyError",
    "export_to_yaml",
    "export_to_json",
]
__version__ = "4.0.0rc1"
