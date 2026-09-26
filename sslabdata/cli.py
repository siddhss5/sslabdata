"""
Command-line interface for sslabdata.

Copyright (c) 2024 Personal Robotics Laboratory, University of Washington
Author: Siddhartha Srinivasa <siddh@cs.washington.edu>
MIT License - see LICENSE file for details.
"""

import argparse
import json
import sys

import yaml

from .config import ConfigurationError, LabDataConfig
from .assembler import assemble_result, unresolved_name_diagnostics
from .diagnostics import ERROR, diagnostic, record, severity
from .exporters import export_to_yaml, export_to_json

# A configuration sslabdata cannot open or cannot read at all. Both are fatal
# at load; the second keeps the reading library's words as its prose.
CONFIG_NOT_FOUND = "CONFIG-NOT-FOUND"
CONFIG_UNREADABLE = "CONFIG-UNREADABLE"

# What reading a configuration can fail with for reasons of the input, not of
# the program: a file that cannot be opened, is not UTF-8 or is not YAML. Any
# other exception is a defect and is left to propagate.
CONFIG_READ_ERRORS = (OSError, UnicodeDecodeError, yaml.YAMLError)


def main(argv=None):
    """Main CLI entry point. ``argv`` defaults to ``sys.argv[1:]``."""
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

    args = parser.parse_args(argv)

    if not args.output and not args.validate and not args.unresolved:
        parser.error("One of --output, --validate, or --unresolved is required")

    # With --validate or --unresolved, --format names how the diagnostics are
    # printed; with --output alone it names the document's format.
    as_json = args.format == 'json' and (args.validate or args.unresolved)

    try:
        config = LabDataConfig.from_yaml(args.config)
    except FileNotFoundError:
        stop(diagnostic(CONFIG_NOT_FOUND, args.config, None, None,
                        "configuration file not found"), "Error: ", as_json)
    except ConfigurationError as e:
        stop(e.args[0], "Error loading configuration: ", as_json)
    except CONFIG_READ_ERRORS as e:
        stop(diagnostic(CONFIG_UNREADABLE, args.config, None, None, str(e)),
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
        stop(diagnostic(CONFIG_UNREADABLE, args.config, None, None, str(e)),
             "Error loading configuration: ", as_json)
    data = result.data
    found = result.diagnostics

    def level(line):
        return severity(line, validating=args.validate, strict=args.strict)
    errors = [line for line in found if level(line) == ERROR]
    warnings = [line for line in found if level(line) != ERROR]

    if as_json:
        records = [record(line, level(line)) for line in found]
        if args.unresolved and not args.validate:
            records += [record(line, level(line)) for line in
                        unresolved_name_diagnostics(data.works,
                                                    result.unresolved_authors,
                                                    config.bib_dir)]
        print(json.dumps(records, indent=2, ensure_ascii=False))
        if errors:
            sys.exit(1)
        return

    if args.validate:
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
            sys.exit(1)
        print("\nValidation passed.")
        return

    # Outside --validate, an error still stops the run: a user must not be
    # able to produce a document by skipping validation. Nothing is written,
    # and a file already at --output is left as it was.
    for error in errors:
        print(error, file=sys.stderr)
    for message in warnings:
        print(f"Warning: {message}", file=sys.stderr)
    if errors:
        sys.exit(1)

    if args.unresolved:
        if not config.people_file:
            print("Author resolution is not configured (no people_file).")
            return
        if not result.unresolved_authors:
            print("All authors resolved.")
        else:
            print(f"Unresolved authors ({len(result.unresolved_authors)}):")
            for name in sorted(result.unresolved_authors):
                print(f"  {name}")
        return

    export_func = export_to_yaml if args.format == 'yaml' else export_to_json
    export_func(data, args.output)

    print(f"Wrote {args.output}")
    print(f"  {len(data.works)} works, "
          f"{len(data.people)} people, "
          f"{len(data.projects)} projects")


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
