"""
Command-line interface for sslabdata.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import argparse
import json
import os
import shlex
import sys
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import yaml

from .config import ConfigurationError, LabDataConfig
from .assembler import assemble_result, unresolved_name_diagnostics
from .diagnostics import (
    ERROR, Diagnostic, diagnostic, in_report_order, record, severity,
)
from .exporters import _write, export_to_yaml, export_to_json, serialize

CONFIG_NOT_FOUND = "CONFIG-NOT-FOUND"
CONFIG_UNREADABLE = "CONFIG-UNREADABLE"

# What reading a configuration can fail with for reasons of the input, not of
# the program: a file that cannot be opened, is not UTF-8 or is not YAML. Any
# other exception is a defect and is left to propagate.
CONFIG_READ_ERRORS = (OSError, UnicodeDecodeError, yaml.YAMLError)

OUTPUT_WRITE_FAILED = "OUTPUT-WRITE-FAILED"

INIT_FILE_EXISTS = "INIT-FILE-EXISTS"
INIT_PATH_WRONG_KIND = "INIT-PATH-WRONG-KIND"
INIT_PATH_OUTSIDE_DIR = "INIT-PATH-OUTSIDE-DIR"
INIT_WRITE_FAILED = "INIT-WRITE-FAILED"

# The files `init` writes, relative to its directory, in the order it writes
# them. Each is package data under sslabdata/templates/init/.
INIT_FILES = ("lab.yaml", "bib/publications.bib", "people.yaml",
              "projects.yaml", "collaborators.yaml")


def main(argv=None):
    """Main CLI entry point. ``argv`` defaults to ``sys.argv[1:]``.

    ``init`` as the first argument is the one subcommand. Any other command
    line is parsed as it always was: the flag form takes no positional
    argument, so no command line it accepted begins with ``init``.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["init"]:
        init(argv[1:])
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.output and not args.validate and not args.unresolved:
        parser.error("One of --output, --validate, or --unresolved is required")

    # --format has two meanings (SPEC.md §1).
    as_json = args.format == 'json' and (args.validate or args.unresolved)

    config, result = load(args.config, as_json)
    found = result.diagnostics

    # Serialized as --output would, so --validate cannot pass a document
    # --output refuses.
    if args.validate:
        try:
            serialize(result.data, args.format)
        except ConfigurationError as e:
            found = in_report_order([*found, located(e, args.config)])

    def level(line):
        return severity(line, validating=args.validate, strict=args.strict)
    errors = [line for line in found if level(line) == ERROR]
    warnings = [line for line in found if level(line) != ERROR]

    if as_json:
        status = report_json(found, level, errors, config, result,
                             args.unresolved and not args.validate)
    elif args.validate:
        status = report_validation(result, errors, warnings)
    else:
        status = report_to_stderr(errors, warnings)
        if not status and args.unresolved:
            status = report_unresolved(config, result)
        elif not status:
            status = write_output(result.data, args)
    if status:
        sys.exit(status)


def build_parser() -> argparse.ArgumentParser:
    """The command line's options, help and examples."""
    parser = argparse.ArgumentParser(
        description='Assemble academic lab data from BibTeX and YAML',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate YAML output
  sslabdata --config lab.yaml --output lab.yml

  # Generate JSON output
  sslabdata --config lab.yaml --format json --output lab.json

  # Validate configuration and data
  sslabdata --config lab.yaml --validate

  # Show unresolved author names
  sslabdata --config lab.yaml --unresolved

  # Fail on every coded diagnostic that can be an error, as JSON records
  sslabdata --config lab.yaml --validate --strict --format json

  # Start a new lab: write a lab.yaml and sample inputs into mylab/
  sslabdata init mylab
        """
    )

    parser.add_argument(
        '--config', required=True,
        help='Path to YAML configuration file (lab.yaml)'
    )
    parser.add_argument(
        '--format', choices=['yaml', 'json'], default='yaml',
        help='Output format (default: yaml). With --output, the document; '
             'with --validate or --unresolved, json prints the diagnostics '
             'as one JSON array'
    )
    parser.add_argument(
        '--output',
        help='Output file path'
    )
    parser.add_argument(
        '--validate', action='store_true',
        help='Validate configuration and report issues, then exit'
    )
    parser.add_argument(
        '--unresolved', action='store_true',
        help='Show unresolved author names, then exit'
    )
    parser.add_argument(
        '--strict', action='store_true',
        help='Treat every coded diagnostic as an error, except those about '
             'authors who matched no lab member and redefined @string macros'
    )
    return parser


def build_init_parser() -> argparse.ArgumentParser:
    """The ``init`` subcommand's options and help."""
    parser = argparse.ArgumentParser(
        prog='sslabdata init',
        description='Write a minimal, valid starting point: lab.yaml, '
                    'bib/publications.bib, people.yaml, projects.yaml and '
                    'collaborators.yaml, each holding one fictional record.',
    )
    parser.add_argument(
        'dir', nargs='?', default='.', metavar='DIR',
        help='Directory to write into, created if missing '
             '(default: the current directory)'
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Overwrite the files init writes if they exist; nothing else '
             'is touched'
    )
    return parser


def init(argv) -> None:
    """``sslabdata init [DIR] [--force]``: copy the starting point into DIR.

    Every problem is found before anything is written, so a refused run
    writes nothing. Exits 1 on a coded diagnostic, 2 on a usage error.
    """
    args = build_init_parser().parse_args(argv)
    target = Path(args.dir)

    def fail(code: str, path, message: str) -> None:
        print(diagnostic(code, str(path), None, None, message), file=sys.stderr)

    if os.path.lexists(target) and not target.is_dir():
        fail(INIT_PATH_WRONG_KIND, target, "is not a directory")
        sys.exit(1)

    root = Path(os.path.realpath(target))
    problems = 0
    for name in INIT_FILES:
        dest = target / name
        parent = dest.parent
        if os.path.lexists(parent) and not parent.is_dir():
            fail(INIT_PATH_WRONG_KIND, parent, "is not a directory")
        elif not Path(os.path.realpath(parent)).is_relative_to(root):
            # A symlinked subdirectory would put the file outside DIR.
            fail(INIT_PATH_OUTSIDE_DIR, dest,
                 f"resolves outside {str(target)!r}")
        elif not os.path.lexists(dest):
            continue
        elif os.path.isdir(dest) or not (dest.is_file()
                                         or os.path.islink(dest)):
            # Not overwritten even with --force: a directory, or a file
            # that is not a regular one. A symlink is replaced itself, and
            # what it points to is left alone.
            fail(INIT_PATH_WRONG_KIND, dest, "is not a regular file")
        elif not args.force:
            fail(INIT_FILE_EXISTS, dest,
                 "already exists; --force overwrites it")
        else:
            continue
        problems += 1
    if problems:
        sys.exit(1)

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        fail(INIT_WRITE_FAILED, target,
             f"the directory could not be created: {e.strerror or e}")
        sys.exit(1)
    for name in INIT_FILES:
        dest = target / name
        source = files("sslabdata") / "templates" / "init"
        for part in name.split("/"):
            source = source / part
        text = source.read_text(encoding="utf-8")
        try:
            write_new_file(dest, text, overwrite=args.force)
        except OSError as e:
            fail(INIT_WRITE_FAILED, dest,
                 f"the file could not be written: {e.strerror or e}")
            sys.exit(1)
        print(f"Wrote {dest}")

    here = root == Path(os.path.realpath(os.getcwd()))
    command = "sslabdata --config lab.yaml --validate --strict"
    print("\nNext, check it:")
    print(f"  {command}" if here else f"  cd {shlex.quote(args.dir)} && {command}")


def write_new_file(dest: Path, text: str, overwrite: bool) -> None:
    """Write ``text`` to ``dest``, whole or not at all.

    With ``overwrite``, the file replaces any at ``dest`` atomically, and a
    failed write leaves the old one as it was. Without it, ``dest`` is
    created only if nothing is there, even if something appeared since it
    was checked, and a failed write removes what it created.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        _write(str(dest), text)
        return
    f = open(dest, "x", encoding="utf-8")
    try:
        with f:
            f.write(text)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def load(path: str, as_json: bool):
    """Load the configuration at ``path`` and assemble it, as
    ``(config, result)``; a load failure is reported and exits 1."""
    try:
        config = LabDataConfig.from_yaml(path)
    except FileNotFoundError:
        stop(diagnostic(CONFIG_NOT_FOUND, path, None, None,
                        "configuration file not found"), "Error: ", as_json)
    except ConfigurationError as e:
        stop(e.args[0], "Error loading configuration: ", as_json)
    except CONFIG_READ_ERRORS as e:
        stop(diagnostic(CONFIG_UNREADABLE, path, None, None, str(e)),
             "Error loading configuration: ", as_json)

    # An input file that exists but cannot be read (permissions, say) is the
    # one failure the loaders leave for here; its message names the file.
    try:
        result = assemble_result(config)
    except OSError as e:
        stop(diagnostic(CONFIG_UNREADABLE, path, None, None, str(e)),
             "Error loading configuration: ", as_json)
    return config, result


def report_json(found, level, errors, config, result,
                with_unresolved: bool) -> int:
    """Print the diagnostics as one JSON array on standard output, with the
    unresolved names too when ``with_unresolved``; 1 if any is an error."""
    records = [record(line, level(line)) for line in found]
    if with_unresolved:
        records += [record(line, level(line)) for line in
                    unresolved_name_diagnostics(result.data.works,
                                                result.unresolved_authors,
                                                config.bib_dir)]
    print(json.dumps(records, indent=2, ensure_ascii=False))
    return 1 if errors else 0


def report_validation(result, errors, warnings) -> int:
    """Print the --validate report on standard output; 1 if any error."""
    data = result.data
    print(f"Works: {len(data.works)}")
    print(f"People: {len(data.people)}")
    print(f"Projects: {len(data.projects)}")

    if result.unresolved_authors:
        print(f"\nUnresolved authors ({len(result.unresolved_authors)}):")
        for name in sorted(result.unresolved_authors):
            print(f"  - {name}")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")

    if errors:
        print(f"\nBibliography errors ({len(errors)}):")
        for error in errors:
            print(f"  - {error}")
        print(f"\nValidation found {len(errors)} error(s).")
        return 1
    print("\nValidation passed.")
    return 0


def report_to_stderr(errors, warnings) -> int:
    """Print the diagnostics on standard error; 1 if any is an error.

    An error stops the run outside --validate too, so skipping validation
    cannot produce a document.
    """
    for error in errors:
        print(error, file=sys.stderr)
    for message in warnings:
        print(f"Warning: {message}", file=sys.stderr)
    return 1 if errors else 0


def report_unresolved(config, result) -> int:
    """Print the --unresolved report on standard output."""
    if not config.people_file:
        print("Author resolution is not configured (no people_file).")
        return 0
    if not result.unresolved_authors:
        print("All authors resolved.")
    else:
        print(f"Unresolved authors ({len(result.unresolved_authors)}):")
        for name in sorted(result.unresolved_authors):
            print(f"  {name}")
    return 0


def write_output(data, args) -> int:
    """Write the document to --output in --format; 1 if it could not be.

    An `OSError` names the path it refused only when that is not beside
    --output: a name beside it is the random temporary file, which means
    nothing to the user.
    """
    export_func = export_to_yaml if args.format == 'yaml' else export_to_json
    try:
        export_func(data, args.output)
    except ConfigurationError as e:
        # What serializing refuses, reported as --validate reports it.
        print(located(e, args.config), file=sys.stderr)
        return 1
    except OSError as e:
        reason = e.strerror or str(e)
        if e.filename and (Path(os.fsdecode(e.filename)).parent
                           != Path(args.output).parent):
            reason += f": '{os.fsdecode(e.filename)}'"
        print(diagnostic(OUTPUT_WRITE_FAILED, args.output, None, None,
                         f"the document could not be written: {reason}"),
              file=sys.stderr)
        return 1

    print(f"Wrote {args.output}")
    print(f"  {len(data.works)} works, "
          f"{len(data.people)} people, "
          f"{len(data.projects)} projects")
    return 0


def located(error: ConfigurationError, config: str) -> Diagnostic:
    """The diagnostic a document refused while it was serialized carries,
    located at ``config`` when it names no file: `LabData.to_dict()` cannot
    know which file its values came from."""
    line = error.args[0]
    return line if line.file else replace(line, file=config)


def stop(line, prefix: str, as_json: bool) -> None:
    """Report a configuration that did not load, and exit 1: as text on
    standard error after ``prefix``, or as a one-record JSON array."""
    if as_json:
        print(json.dumps([record(line, ERROR)], indent=2, ensure_ascii=False))
    else:
        print(f"{prefix}{line}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
