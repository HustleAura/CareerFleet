#!/usr/bin/env python3
"""Tailor the base resume inventory to a specific job description.

One application lives in one folder under `roles/<company>-<title>-<date>/`,
and the rendered artifacts repeat that slug so a PDF is identifiable once it
leaves the folder:

    jd.txt            the job description, fetched or pasted
    jd_analysis.json  requirements the agent extracted from the JD
    tailored.json     the agent's bullet selection (see templates/tailored.schema.json)
    <slug>.tex        rendered from tailored.json + templates/resume_template.tex
    <slug>.pdf        compiled with pdflatex, same engine Overleaf uses
    notes.md          scratch

The agent never writes LaTeX. It writes plain text with `**bold**` markers into
tailored.json; this script owns every byte of the .tex. That keeps the template
un-injectable and the layout fixed.

Anti-fabrication invariant: every piece of prose carries a `source_id` resolving
to an entry in resume_base.md. Unknown ids, `strength: weak` sources with open
gaps, `verbatim` claims that don't match the source, and skills absent from the
inventory all fail the render.
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES_DIR = ROOT / "roles"
TEMPLATES_DIR = ROOT / "templates"
TEMPLATE_PATH = TEMPLATES_DIR / "resume_template.tex"
BASE_PATH = ROOT / "resume_base.md"

SCHEMA_VERSION = 1
TRANSFORMS = ("verbatim", "rephrased", "reweighted")
PDFLATEX_PASSES = 2


class TailorError(Exception):
    pass


# --- primitives -------------------------------------------------------------


def fail(message):
    raise TailorError(message)


def rel(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT.parent))
    except ValueError:
        return str(path)


def read_json(path):
    if not path.exists():
        fail(f"missing {rel(path)}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{rel(path)} is not valid JSON: {exc}")


def slugify(*parts):
    joined = "-".join(parts)
    slug = re.sub(r"[^a-z0-9]+", "-", joined.lower()).strip("-")
    if not slug:
        fail("could not build a slug from the given company and title")
    return slug


def role_dir(slug):
    path = ROLES_DIR / slug
    if not path.is_dir():
        fail(f"no such role: {slug}. Run `tailor.py status` to list roles.")
    return path


# --- resume_base.md ---------------------------------------------------------

ENTRY_HEADING = re.compile(r"^###\s+(\S+)")
ID_FIELD = re.compile(r"^id:\s*(\S+)")
STRENGTH_FIELD = re.compile(r"^strength:\s*(\S+)")
GAP_ITEM = re.compile(r"^\s+-\s+\S")


class BaseEntry:
    def __init__(self, entry_id):
        self.id = entry_id
        self.strength = None
        self.bullet = None
        self.gap_count = 0


def parse_base(path=BASE_PATH):
    """Extract ids, strengths and bullet text from resume_base.md.

    Deliberately regex-based rather than a YAML dependency: this only needs the
    handful of fields the render gates on, and the file stays human-editable.
    """
    if not path.exists():
        fail(f"missing {rel(path)}")

    entries = {}
    current = None
    mode = None  # None | "bullet" | "gaps"
    bullet_lines = []

    def flush_bullet():
        nonlocal bullet_lines
        if current and bullet_lines:
            current.bullet = " ".join(line.strip() for line in bullet_lines).strip()
        bullet_lines = []

    for line in path.read_text(encoding="utf-8").splitlines():
        heading = ENTRY_HEADING.match(line)
        if heading:
            flush_bullet()
            mode = None
            current = BaseEntry(heading.group(1))
            entries[current.id] = current
            continue

        if current is not None and mode == "bullet":
            if line.startswith((" ", "\t")) and line.strip():
                bullet_lines.append(line)
                continue
            flush_bullet()
            mode = None

        if current is not None and mode == "gaps":
            if GAP_ITEM.match(line):
                current.gap_count += 1
                continue
            mode = None

        id_match = ID_FIELD.match(line)
        if id_match:
            flush_bullet()
            mode = None
            current = BaseEntry(id_match.group(1))
            entries[current.id] = current
            continue

        if current is None:
            continue

        strength = STRENGTH_FIELD.match(line)
        if strength:
            current.strength = strength.group(1)
        elif line.startswith("bullet:"):
            inline = line[len("bullet:"):].strip()
            if inline and inline not in (">-", ">", "|", "|-"):
                current.bullet = inline.strip("\"'")
            else:
                mode = "bullet"
        elif line.startswith("gaps:"):
            mode = "gaps" if line.strip() == "gaps:" else None

    flush_bullet()
    return entries


SKILL_INLINE = re.compile(r"^\s*items:\s*\[(.+)\]\s*$")
SKILL_BLOCK = re.compile(r"^\s*items:\s*$")
SKILL_ITEM = re.compile(r"^\s+-\s+(.+?)\s*$")


def parse_base_skills(path=BASE_PATH):
    """Every technology the inventory permits, normalised for comparison."""
    allowed = set()
    in_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        inline = SKILL_INLINE.match(line)
        if inline:
            in_block = False
            allowed.update(item.strip() for item in inline.group(1).split(","))
            continue
        if SKILL_BLOCK.match(line):
            in_block = True
            continue
        if in_block:
            item = SKILL_ITEM.match(line)
            if item:
                allowed.add(item.group(1))
            else:
                in_block = False
    return {normalise(item) for item in allowed if item}


def normalise(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# --- LaTeX ------------------------------------------------------------------

LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
SPECIAL_RE = re.compile("|".join(re.escape(char) for char in LATEX_SPECIALS))
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
URL_SPECIALS = {"%": r"\%", "#": r"\#"}
URL_RE = re.compile("|".join(re.escape(char) for char in URL_SPECIALS))


def typeset(text, where=""):
    """Escape LaTeX specials, then promote `**bold**`. Order matters."""
    if not isinstance(text, str):
        fail(f"{where}: expected a string, got {type(text).__name__}")
    escaped = SPECIAL_RE.sub(lambda m: LATEX_SPECIALS[m.group()], text)
    marked = BOLD_RE.sub(lambda m: r"\textbf{" + m.group(1) + "}", escaped)
    if "**" in marked:
        fail(f"{where}: unbalanced ** in {text!r}")
    return marked


def typeset_url(url, where=""):
    if not isinstance(url, str):
        fail(f"{where}: expected a URL string")
    return URL_RE.sub(lambda m: URL_SPECIALS[m.group()], url)


# --- validation -------------------------------------------------------------


def require_keys(obj, keys, where):
    if not isinstance(obj, dict):
        fail(f"{where}: expected an object")
    missing = [key for key in keys if key not in obj]
    if missing:
        fail(f"{where}: missing {', '.join(missing)}")


def check_sourced(node, entries, where, allow_weak=False):
    """Enforce the anti-fabrication invariant on one piece of prose."""
    require_keys(node, ("source_id", "transform", "text"), where)
    source_id = node["source_id"]
    transform = node["transform"]

    if transform not in TRANSFORMS:
        fail(f"{where}: transform must be one of {', '.join(TRANSFORMS)}, got {transform!r}")

    entry = entries.get(source_id)
    if entry is None:
        fail(f"{where}: source_id {source_id!r} is not in resume_base.md")

    if entry.strength == "weak" and entry.gap_count and not allow_weak:
        fail(
            f"{where}: {source_id} is strength:weak with {entry.gap_count} open gap(s). "
            "Resolve them in resume_base.md before using it."
        )

    text = node["text"]
    if not isinstance(text, str) or not text.strip():
        fail(f"{where}: text is empty")

    if transform == "verbatim" and entry.bullet:
        if collapse(text) != collapse(entry.bullet):
            fail(f"{where}: transform is 'verbatim' but the text differs from {source_id}")

    return typeset(text, where)


def collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def build_context(payload, entries, allowed_skills, allow_weak=False):
    if payload.get("schema_version") != SCHEMA_VERSION:
        fail(f"tailored.json: schema_version must be {SCHEMA_VERSION}")

    require_keys(
        payload,
        ("role", "contact", "summary", "experience", "education", "skills"),
        "tailored.json",
    )

    contact = payload["contact"]
    require_keys(
        contact,
        ("name", "email", "phone", "linkedin", "github", "codeforces", "codeforces_rating"),
        "contact",
    )

    context = {
        "contact": {
            "name": typeset(contact["name"], "contact.name"),
            "email": typeset_url(contact["email"], "contact.email"),
            "phone": typeset(contact["phone"], "contact.phone"),
            "linkedin": typeset_url(contact["linkedin"], "contact.linkedin"),
            "github": typeset_url(contact["github"], "contact.github"),
            "codeforces": typeset_url(contact["codeforces"], "contact.codeforces"),
            "codeforces_rating": typeset(
                contact["codeforces_rating"], "contact.codeforces_rating"
            ),
        },
        "summary": check_sourced(payload["summary"], entries, "summary", allow_weak),
        "experience": [],
        "education": [],
        "projects": [],
        "skills": [],
        "competitive_programming": [],
    }

    if not payload["experience"]:
        fail("tailored.json: experience must have at least one role")

    for index, role in enumerate(payload["experience"]):
        where = f"experience[{index}]"
        require_keys(role, ("id", "title", "location", "org", "dates", "bullets"), where)
        if role["id"] not in entries:
            fail(f"{where}: id {role['id']!r} is not in resume_base.md")
        if not role["bullets"]:
            fail(f"{where}: a role needs at least one bullet")
        context["experience"].append(
            {
                "title": typeset(role["title"], f"{where}.title"),
                "location": typeset(role["location"], f"{where}.location"),
                "org": typeset(role["org"], f"{where}.org"),
                "dates": typeset(role["dates"], f"{where}.dates"),
                "bullets": [
                    check_sourced(bullet, entries, f"{where}.bullets[{n}]", allow_weak)
                    for n, bullet in enumerate(role["bullets"])
                ],
            }
        )

    for index, school in enumerate(payload["education"]):
        where = f"education[{index}]"
        require_keys(school, ("institution", "location", "degree", "dates"), where)
        context["education"].append(
            {key: typeset(school[key], f"{where}.{key}") for key in
             ("institution", "location", "degree", "dates")}
        )

    for index, project in enumerate(payload.get("projects") or []):
        where = f"projects[{index}]"
        require_keys(project, ("title", "link", "date", "bullets"), where)
        context["projects"].append(
            {
                "title": typeset(project["title"], f"{where}.title"),
                "link": typeset_url(project["link"], f"{where}.link"),
                "date": typeset(project["date"], f"{where}.date"),
                "bullets": [
                    check_sourced(bullet, entries, f"{where}.bullets[{n}]", allow_weak)
                    for n, bullet in enumerate(project["bullets"])
                ],
            }
        )

    for index, category in enumerate(payload["skills"]):
        where = f"skills[{index}]"
        require_keys(category, ("name", "items"), where)
        if not category["items"]:
            fail(f"{where}: a skills category needs at least one item")
        for item in category["items"]:
            if normalise(item) not in allowed_skills:
                fail(
                    f"{where}: {item!r} is not in the SKL-01 inventory. "
                    "Add it to resume_base.md first if you can defend it."
                )
        context["skills"].append(
            {
                "name": typeset(category["name"], f"{where}.name"),
                # Not "items": Jinja would resolve category.items to the dict method.
                "listing": ", ".join(
                    typeset(item, f"{where}.items") for item in category["items"]
                ),
            }
        )

    for index, item in enumerate(payload.get("competitive_programming") or []):
        context["competitive_programming"].append(
            typeset(item, f"competitive_programming[{index}]")
        )

    return context


# --- rendering --------------------------------------------------------------


def load_template():
    try:
        from jinja2 import Environment, StrictUndefined
    except ImportError:
        fail("Jinja2 is not installed. Run: pip install -r ResumeAgent/requirements.txt")

    if not TEMPLATE_PATH.exists():
        fail(f"missing {rel(TEMPLATE_PATH)}")

    env = Environment(
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return env.from_string(TEMPLATE_PATH.read_text(encoding="utf-8"))


MISSING_STY = re.compile(r"File [`']([^'`]+\.sty)' not found")
PAGE_COUNT = re.compile(r"Output written on .*?\((\d+) pages?")
PYTHON_REPR = re.compile(r"<(?:built-in |bound )?(?:method|function|object|class)\b[^>]*>")


def run_pdflatex(directory, tex_name):
    log = ""
    for _ in range(PDFLATEX_PASSES):
        try:
            result = subprocess.run(
                [
                    "pdflatex",
                    "-halt-on-error",
                    "-interaction=nonstopmode",
                    "-file-line-error",
                    tex_name,
                ],
                cwd=directory,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            fail(
                "pdflatex not found. Install BasicTeX:\n"
                "  brew install --cask basictex\n"
                '  eval "$(/usr/libexec/path_helper)"\n'
                "  sudo tlmgr update --self\n"
                "  sudo tlmgr install titlesec marvosym enumitem fancyhdr preprint"
            )
        log = result.stdout + result.stderr
        if result.returncode != 0:
            return False, log
    return True, log


def resolve_package(sty):
    """Map a missing .sty filename to the TeX Live package that ships it."""
    try:
        result = subprocess.run(
            ["tlmgr", "search", "--global", "--file", f"/{sty}"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    for line in result.stdout.splitlines():
        if line.endswith(":") and not line.startswith((" ", "\t")):
            return line[:-1].strip()
    return None


def handle_missing_package(log, auto_install):
    match = MISSING_STY.search(log)
    if not match:
        return False
    sty = match.group(1)
    package = resolve_package(sty) or Path(sty).stem
    command = f"sudo tlmgr install {package}"

    if not auto_install:
        fail(f"missing LaTeX package: {sty}\nRun:\n  {command}\nThen re-run render.")

    print(f"installing missing package {package} (requires sudo)")
    result = subprocess.run(["sudo", "tlmgr", "install", package])
    if result.returncode != 0:
        fail(f"`{command}` failed")
    return True


def cleanup(directory):
    for pattern in ("*.aux", "*.log", "*.out", "*.synctex.gz"):
        for path in directory.glob(pattern):
            path.unlink()


def tail(log, lines=25):
    return "\n".join(log.splitlines()[-lines:])


# --- HTML -------------------------------------------------------------------


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.chunks = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif tag in ("p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4"):
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self.skipping and data.strip():
            self.chunks.append(data.strip())

    def text(self):
        joined = " ".join(self.chunks)
        joined = re.sub(r" *\n *", "\n", joined)
        return re.sub(r"\n{3,}", "\n\n", joined).strip()


def fetch_url(url):
    if not url.lower().startswith(("http://", "https://")):
        fail("only http(s) URLs are supported")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="replace")
    parser = TextExtractor()
    parser.feed(body)
    return parser.text()


# --- commands ---------------------------------------------------------------


def cmd_new(args):
    stamp = args.date or date.today().isoformat().replace("-", "")
    slug = slugify(args.company, args.title, stamp)
    directory = ROLES_DIR / slug
    if directory.exists():
        fail(f"role {slug} already exists")
    directory.mkdir(parents=True)

    if args.jd_url:
        jd = fetch_url(args.jd_url)
        source = args.jd_url
    elif args.jd_file:
        jd = Path(args.jd_file).read_text(encoding="utf-8")
        source = rel(args.jd_file)
    else:
        jd = ""
        source = "pending"

    (directory / "jd.txt").write_text(jd, encoding="utf-8")
    (directory / "notes.md").write_text(
        f"# {args.company} — {args.title}\n\nJD source: {source}\n", encoding="utf-8"
    )
    print(f"created {rel(directory)}")
    if not jd:
        print("jd.txt is empty — paste the JD in, or run `tailor.py fetch` with a URL")
    return slug


def cmd_fetch(args):
    directory = role_dir(args.slug)
    text = fetch_url(args.url)
    if not text:
        fail("fetched page had no extractable text — paste the JD manually instead")
    (directory / "jd.txt").write_text(text, encoding="utf-8")
    print(f"wrote {rel(directory / 'jd.txt')} ({len(text.split())} words)")


def cmd_validate(args):
    directory = role_dir(args.slug)
    payload = read_json(directory / "tailored.json")
    build_context(payload, parse_base(), parse_base_skills(), args.allow_weak)
    print(f"{args.slug}: tailored.json is valid")


def cmd_render(args):
    directory = role_dir(args.slug)
    payload = read_json(directory / "tailored.json")
    context = build_context(payload, parse_base(), parse_base_skills(), args.allow_weak)

    tex = load_template().render(**context)
    leaked = PYTHON_REPR.search(tex)
    if leaked:
        fail(f"template bug: a Python object leaked into the LaTeX ({leaked.group()})")

    tex_path = directory / f"{directory.name}.tex"
    tex_path.write_text(tex, encoding="utf-8")
    print(f"wrote {rel(tex_path)}")

    ok, log = run_pdflatex(directory, tex_path.name)
    if not ok and handle_missing_package(log, args.auto_install):
        ok, log = run_pdflatex(directory, tex_path.name)

    if not ok:
        log_path = directory / "pdflatex.log"
        log_path.write_text(log, encoding="utf-8")
        fail(f"pdflatex failed. Last lines:\n{tail(log)}\n\nFull log: {rel(log_path)}")

    pages = PAGE_COUNT.search(log)
    cleanup(directory)
    print(f"wrote {rel(directory / (directory.name + '.pdf'))}")
    if pages:
        count = int(pages.group(1))
        print(f"pages: {count}")
        if count > 1:
            print("WARNING: resume is over one page — drop the lowest-ranked bullet")


def cmd_status(args):
    if not ROLES_DIR.exists():
        print("no roles yet")
        return
    slugs = sorted(p.name for p in ROLES_DIR.iterdir() if p.is_dir())
    if args.slug:
        slugs = [s for s in slugs if s == args.slug] or fail(f"no such role: {args.slug}")
    if not slugs:
        print("no roles yet")
        return
    for slug in slugs:
        directory = ROLES_DIR / slug
        have = [
            name
            for name in (
                "jd.txt",
                "jd_analysis.json",
                "tailored.json",
                f"{slug}.tex",
                f"{slug}.pdf",
            )
            if (directory / name).exists() and (directory / name).stat().st_size > 0
        ]
        print(f"{slug:<50} {', '.join(have) if have else 'empty'}")


# Baseline-parity only: the current resume predates the gap schema and still carries weak bullets.
WEAK_HELP = (
    "permit strength:weak bullets with open gaps — for golden-baseline parity only, "
    "never for a real application"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="scaffold a role folder")
    new.add_argument("company")
    new.add_argument("title")
    new.add_argument("--date", help="YYYYMMDD, defaults to today")
    new.add_argument("--jd-file")
    new.add_argument("--jd-url")
    new.set_defaults(func=cmd_new)

    fetch = subparsers.add_parser("fetch", help="download a JD into an existing role")
    fetch.add_argument("slug")
    fetch.add_argument("--url", required=True)
    fetch.set_defaults(func=cmd_fetch)

    validate = subparsers.add_parser("validate", help="check tailored.json without rendering")
    validate.add_argument("slug")
    validate.add_argument("--allow-weak", action="store_true", help=WEAK_HELP)
    validate.set_defaults(func=cmd_validate)

    render = subparsers.add_parser(
        "render", help="tailored.json -> <slug>.tex -> <slug>.pdf"
    )
    render.add_argument("slug")
    render.add_argument(
        "--auto-install",
        action="store_true",
        help="install missing LaTeX packages via sudo tlmgr instead of just reporting them",
    )
    render.add_argument("--allow-weak", action="store_true", help=WEAK_HELP)
    render.set_defaults(func=cmd_render)

    status = subparsers.add_parser("status", help="list roles and their artifacts")
    status.add_argument("slug", nargs="?")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    try:
        args.func(args)
    except TailorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
