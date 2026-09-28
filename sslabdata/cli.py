"""
Command-line interface for sslabdata.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa
MIT License - see LICENSE file for details.
"""

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import yaml

from .config import ConfigurationError, LabDataConfig
from .assembler import assemble_result, unresolved_name_diagnostics
from .diagnostics import (
    ERROR, Diagnostic, diagnostic, in_report_order, record, severity,
)
from .exporters import export_to_yaml, export_to_json, serialize

# A configuration sslabdata cannot open or cannot read at all. Both are fatal
# at load; the second keeps the reading library's words as its prose.
CONFIG_NOT_FOUND = "CONFIG-NOT-FOUND"
CONFIG_UNREADABLE = "CONFIG-UNREADABLE"

# What reading a configuration can fail with for reasons of the input, not of
# the program: a file that cannot be opened, is not UTF-8 or is not YAML. Any
# other exception is a defect and is left to propagate.
CONFIG_READ_ERRORS = (OSError, UnicodeDecodeError, yaml.YAMLError)

# The document could not be written to --output. Fatal: the run exits 1, and
# the file already there, if any, is as it was.
OUTPUT_WRITE_FAILED = "OUTPUT-WRITE-FAILED"


def main(argv=None):
    """Main CLI entry point. ``argv`` defaults to ``sys.argv[1:]``."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.output and not args.validate and not args.unresolved:
        parser.error("One of --output, --validate, or --unresolved is required")

    # With --validate or --unresolved, --format names how the diagnostics are
    # printed; with --output alone it names the document's format.
    as_json = args.format == 'json' and (args.validate or args.unresolved)

    config, result = load(args.config, as_json)
    found = result.diagnostics

    # --validate builds the document in memory, in --format, with the code
    # --output writes it with, so it cannot pass a document --output would
    # refuse. What it cannot find is a failure of the write itself.
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

    # `assemble_result()` raises `ConfigurationError` for an absolute or
    # escaping `bib_files` name, but `from_yaml()` above has already rejected
    # that with the file named, so it cannot happen here: the check is for
    # callers who built a configuration themselves.
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

    Outside --validate, an error still stops the run: a user must not be
    able to produce a document by skipping validation. Nothing is written,
    and a file already at --output is left as it was.
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

    A destination the system will not let sslabdata write -- a directory,
    a path under a file, a directory without write permission -- is an
    input failure, not a defect. The write is atomic, so nothing has
    changed. The error names the temporary file when the write itself
    failed; its name is random and means nothing to the user, so it is
    given only when it is not beside --output (a parent that is a file).
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
    """Report a configuration that did not load, and exit 1.

    As text, on standard error after ``prefix``; as JSON, the one record on
    standard output, so a JSON reader always receives an array.
    """
    if as_json:
        print(json.dumps([record(line, ERROR)], indent=2, ensure_ascii=False))
    else:
        print(f"{prefix}{line}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
