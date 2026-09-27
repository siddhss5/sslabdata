"""tests/COVERAGE.md names a fixture and a test for each case, and test-suite
hygiene: tests reach sslabdata only through its public names."""

import ast
import re

import sslabdata

from .support import CORPUS, EXPECTED, REPO_ROOT, TESTS_DIR

ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|[^|]*\|[^|]*\|\s*`([^`]+)`\s*\|([^|]*)\|", re.MULTILINE)
TEST_RE = re.compile(r"`(\w+\.py)::(\w+)`")


def mentions(text, case_id):
    return re.search(r"(?<![\w.])" + re.escape(case_id) + r"(?![\w.])", text)


def test_every_row_appears_in_its_fixture_and_a_test():
    """Each case ID is unique, is in the fixture it names, and is owned by a test.

    A fixture outside tests/corpus (the demo, a schema) carries no markers,
    so for those the named file only has to exist. A test named in the Test
    column has to be defined in the file it names, and the ID has to appear
    in a test or in diagnostics.yaml.
    """
    rows = ROW_RE.findall((TESTS_DIR / "COVERAGE.md").read_text(encoding="utf-8"))
    test_files = [*TESTS_DIR.rglob("test_*.py"), EXPECTED / "diagnostics.yaml"]
    tests = "\n".join(path.read_text(encoding="utf-8") for path in test_files)
    defined = {}
    for path in TESTS_DIR.rglob("test_*.py"):
        defined[path.name] = {node.name for node in ast.walk(ast.parse(
            path.read_text(encoding="utf-8"))) if isinstance(node, ast.FunctionDef)}
    problems = []
    ids = [case_id for case_id, _, _ in rows]
    problems += [f"{case_id}: appears in more than one row"
                 for case_id in sorted({i for i in ids if ids.count(i) > 1})]
    for case_id, fixture, owners in rows:
        path = REPO_ROOT / fixture
        if not path.is_file():
            problems.append(f"{case_id}: no fixture {fixture}")
        elif CORPUS in path.parents and not mentions(
                path.read_bytes().decode("utf-8", errors="replace"), case_id):
            problems.append(f"{case_id}: not in {fixture}")
        named = TEST_RE.findall(owners)
        if not named:
            problems.append(f"{case_id}: names no test as file.py::test_name")
        problems += [f"{case_id}: {name} is not defined in {file}"
                     for file, name in named if name not in defined.get(file, ())]
        if not mentions(tests, case_id):
            problems.append(f"{case_id}: in no test")
    assert rows, "no case rows were read from COVERAGE.md"
    assert not problems, "\n".join(problems)


# --- Test-suite hygiene -----------------------------------------------------

PUBLIC = set(sslabdata.__all__) | {"main"}


def imports(path):
    """(module, name) for each import; name is None for ``import module``."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                yield node.module, alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None


# The adapter: the only place pybtex and pylatexenc may be imported.
ADAPTER = {"sslabdata/parsers/bibtex.py", "sslabdata/parsers/latex.py"}
PARSER_LIBRARIES = {"pybtex", "pylatexenc", "bibtexparser"}


def test_no_test_imports_a_parser_library():
    """Tests check sslabdata's output, never a parser library's objects."""
    offenders = [str(p.relative_to(TESTS_DIR)) for p in TESTS_DIR.rglob("*.py")
                 if any(m.split(".")[0] in PARSER_LIBRARIES for m, _ in imports(p))]
    assert offenders == []


def test_only_the_adapter_imports_a_parser_library():
    """pybtex and pylatexenc stay behind the adapter."""
    offenders = []
    for path in sorted((REPO_ROOT / "sslabdata").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in ADAPTER:
            continue
        for module, _ in imports(path):
            if module.split(".")[0] in PARSER_LIBRARIES:
                offenders.append(f"{relative}: {module}")
    assert offenders == []
    # An empty list has to mean "looked and found none": the adapter itself
    # imports both libraries, so the search above can see one when it is there.
    found = {module.split(".")[0] for path in ADAPTER
             for module, _ in imports(REPO_ROOT / path)}
    assert {"pybtex", "pylatexenc"} <= found


def test_only_unit_tests_import_sslabdata_internals():
    """Outside tests/unit/, tests use only sslabdata's public names and cli.main."""
    offenders = []
    for path in TESTS_DIR.rglob("*.py"):
        if "unit" in path.relative_to(TESTS_DIR).parts:
            continue
        for module, name in imports(path):
            if not module.startswith("sslabdata"):
                continue
            if name is None:
                public = module == "sslabdata"
            else:
                public = name in PUBLIC and (name != "main" or module == "sslabdata.cli")
            if not public:
                offenders.append(f"{path.relative_to(TESTS_DIR)}: {module} {name}")
    assert offenders == []
