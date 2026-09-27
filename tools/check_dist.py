"""Check the metadata of a built wheel and sdist, and write a report.

    python tools/check_dist.py dist                      # report on stdout
    python tools/check_dist.py dist --report report.json

`dist` holds exactly one wheel and one sdist, built once from a clean tree,
for example with `uv build --out-dir dist`. The check reads the metadata inside
each archive, the file an installer and the PyPI project page read, and fails
(exit 1, one line per problem) unless each carries:

- a non-empty long description of type text/markdown;
- the license expression MIT and its LICENSE file, present in the archive;
- Homepage, Repository, Documentation, Issues and Changelog project URLs;
- no author or maintainer email address;
- no relative link target in the long description. PyPI renders the description
  away from the repository, so a relative path, a fragment-only `#anchor` and a
  scheme-relative `//host` all break there. Only http, https and mailto pass.

The report is the metadata that was checked, with the link targets, sorted and
free of timestamps, so two runs over the same archives are byte for byte equal.
Standard library only; the description is scanned for Markdown inline links and
images, reference definitions and HTML `href` / `src`, after fenced code and
code spans are removed.
"""

import argparse
import email
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

URL_LABELS = {"Homepage", "Repository", "Documentation", "Issues", "Changelog"}
FENCE = re.compile(r"^ {0,3}(```|~~~).*?^ {0,3}\1[`~]*[ \t]*$", re.S | re.M)
CODE_SPAN = re.compile(r"(`+).+?\1", re.S)
# A definition's destination may follow on the next line, and may be `<>`.
DEFINITION = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*\n?[ \t]*(?:<([^<>\n]*)>|([^\s<]\S*))", re.M)


class _Attributes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        self.targets += [v for k, v in attrs if k in ("href", "src") and v is not None]

    handle_startendtag = handle_starttag


def inline_targets(text):
    """Yield the destination of each `[text](destination)` and `![alt](destination)`."""
    for opening in re.finditer(r"\]\(", text):
        depth, i = 1, opening.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        inside = text[opening.end():i - 1].strip()
        if inside.startswith("<"):
            yield inside[1:].split(">")[0]
        else:  # what follows the first space is a title; an empty one is a target
            yield inside.split()[0] if inside else ""


def link_targets(markdown):
    text = CODE_SPAN.sub("", FENCE.sub("", markdown))
    html = _Attributes()
    html.feed(text)
    return sorted(set(inline_targets(text)) | {a or b for a, b in DEFINITION.findall(text)} | set(html.targets))


def is_absolute(target):
    parts = urlsplit(target)
    return (parts.scheme in ("http", "https") and bool(parts.netloc)) or parts.scheme == "mailto"


def read_wheel(path):
    with zipfile.ZipFile(path) as z:
        files = z.namelist()
        [name] = [n for n in files if n.endswith(".dist-info/METADATA")]
        return z.read(name).decode("utf-8"), {n.rsplit("/", 1)[-1] for n in files}


def read_sdist(path):
    with tarfile.open(path) as t:
        files = t.getnames()
        [name] = [n for n in files if n.count("/") == 1 and n.endswith("/PKG-INFO")]
        return t.extractfile(name).read().decode("utf-8"), {n.rsplit("/", 1)[-1] for n in files}


def inspect(kind, path, reader):
    """Return (report, problems, description) for one archive."""
    raw, filenames = reader(path)
    meta = email.message_from_string(raw)
    description = meta.get_payload()
    targets = link_targets(description)
    relative = [t for t in targets if not is_absolute(t)]
    urls = dict(v.split(", ", 1) for v in meta.get_all("Project-URL", []))
    problems = []

    def require(ok, message):
        if not ok:
            problems.append(f"{path.name}: {message}")

    require(description.strip(), "no long description")
    require((meta["Description-Content-Type"] or "").split(";")[0].strip() == "text/markdown",
            f"Description-Content-Type is {meta['Description-Content-Type']!r}")
    require(meta["License-Expression"] == "MIT", f"License-Expression is {meta['License-Expression']!r}")
    require(meta.get_all("License-File") == ["LICENSE"] and "LICENSE" in filenames,
            "LICENSE is not declared and shipped")
    require(URL_LABELS <= urls.keys(), f"Project-URL lacks {sorted(URL_LABELS - urls.keys())}")
    require(all(u.startswith("https://") for u in urls.values()), "a Project-URL is not https")
    require(not (meta["Author-email"] or meta["Maintainer-email"]), "an author or maintainer email is present")
    require(not relative, f"relative link targets: {relative}")
    report = {
        "kind": kind,
        "name": meta["Name"],
        "version": meta["Version"],
        "author": meta["Author"],
        "license_expression": meta["License-Expression"],
        "license_files": meta.get_all("License-File"),
        "description_content_type": meta["Description-Content-Type"],
        "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
        "keywords": meta["Keywords"],
        "classifiers": sorted(meta.get_all("Classifier", [])),
        "project_urls": dict(sorted(urls.items())),
        "link_targets": targets,
    }
    return report, problems, description


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dist", type=Path)
    ap.add_argument("--report", type=Path, help="write the JSON report here, not to stdout")
    args = ap.parse_args(argv)
    [wheel] = sorted(args.dist.glob("*.whl"))
    [sdist] = sorted(args.dist.glob("*.tar.gz"))
    results = [inspect("wheel", wheel, read_wheel), inspect("sdist", sdist, read_sdist)]
    problems = [p for _, ps, _ in results for p in ps]
    if results[0][2] != results[1][2]:
        problems.append("the wheel and the sdist carry different long descriptions")
    out = json.dumps([r for r, _, _ in results], indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(out)
    else:
        sys.stdout.write(out)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
