#!/usr/bin/env python3
"""
LaTeX-style Academic Blog Generator
Compile Markdown to beautiful, LaTeX-level HTML.
"""

import hashlib
import json
import subprocess
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

import yaml
import frontmatter
from jinja2 import Environment, FileSystemLoader, select_autoescape
import markdown


CACHE_VERSION = 2


class LatexMacroError(ValueError):
    """Raised when a custom LaTeX macro is invalid or cannot be expanded."""


@dataclass(frozen=True)
class LatexMacro:
    name: str
    args: int
    body: str
    source: str


class BlogBuilder:
    RESERVED_LATEX_COMMANDS = frozenset({
        "begin", "end", "label", "ref", "tag", "nonumber", "notag",
        "frac", "dfrac", "tfrac", "sqrt", "left", "right", "middle",
        "sum", "prod", "int", "iint", "iiint", "oint", "lim",
        "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp",
        "text", "mathrm", "mathit", "mathbf", "mathsf", "mathtt",
        "mathbb", "mathcal", "mathfrak", "boldsymbol", "operatorname",
        "cdot", "times", "leq", "geq", "neq", "in", "notin", "subset",
        "subseteq", "supset", "supseteq", "cup", "cap", "forall", "exists",
    })
    LATEX_MATH_ENVIRONMENTS = frozenset({
        "equation", "equation*", "align", "align*", "aligned", "alignat",
        "alignat*", "gather", "gather*", "multline", "multline*", "split",
        "cases", "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix",
        "Vmatrix", "smallmatrix",
    })
    MAX_MACRO_EXPANSION_DEPTH = 50

    def __init__(self, config_path="config.yaml", skip_pdf=False):
        self.skip_pdf = skip_pdf
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.root = Path(__file__).parent.resolve()
        self.content_dir = self.root / self.config["content_dir"]
        self.output_dir = self.root / self.config["output_dir"]
        self.template_dir = self.root / self.config["template_dir"]
        self.static_dir = self.root / self.config["static_dir"]

        self.jinja = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.jinja.filters["date_format"] = self._filter_date_format
        self.jinja.filters["truncate_words"] = self._filter_truncate_words
        self.jinja.filters["slugify"] = self._slugify
        self.jinja.filters["relative_url"] = lambda u: u.lstrip("/")

        self.md = markdown.Markdown(
            extensions=[
                "meta",
                "toc",
                "tables",
                "fenced_code",
                "footnotes",
                "md_in_html",
                "pymdownx.superfences",
                "pymdownx.arithmatex",
                "pymdownx.highlight",
                "pymdownx.inlinehilite",
                "pymdownx.tabbed",
                "pymdownx.caret",
                "pymdownx.tilde",
            ],
            extension_configs={
                "pymdownx.arithmatex": {"generic": True},
                "pymdownx.highlight": {
                    "css_class": "highlight",
                    "use_pygments": True,
                },
                "toc": {
                    "title": "Table of Contents",
                    "permalink": True,
                    "toc_depth": "2-4",
                },
            },
        )

        self.cache_file = self.root / ".build_cache.json"
        self._cache = self._load_cache()

        self.posts = []
        self.pages = []
        self.tags = defaultdict(list)
        self.categories = defaultdict(list)
        self.archives = defaultdict(list)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _filter_date_format(value, fmt="%Y-%m-%d"):
        if isinstance(value, str):
            try:
                value = datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return value
        if isinstance(value, datetime):
            return value.strftime(fmt)
        return value

    @staticmethod
    def _filter_truncate_words(text, length=50):
        words = re.split(r"\s+", text)
        if len(words) <= length:
            return text
        return " ".join(words[:length]) + "..."

    def _slugify(self, text):
        text = re.sub(r"[^\w\s-]", "", text).strip().lower()
        return re.sub(r"[-\s]+", "-", text)

    def _article_id(self, path: Path) -> str:
        """Generate a short, stable English UUID from the file path.

        Uses UUID5 with the relative path as input — same file always yields
        the same ID, different files never collide. Returns 8 hex chars.
        """
        rel = str(path.relative_to(self.content_dir))
        return uuid.uuid5(uuid.NAMESPACE_URL, rel).hex[:8]

    def _ensure_dir(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)

    def _copy_static(self):
        dst = self.output_dir / "static"
        if dst.exists():
            shutil.rmtree(dst)
        if self.static_dir.exists():
            shutil.copytree(self.static_dir, dst)
        # Also copy content/assets
        src_assets = self.content_dir / "assets"
        if src_assets.exists():
            dst_assets = self.output_dir / "assets"
            if dst_assets.exists():
                shutil.rmtree(dst_assets)
            shutil.copytree(src_assets, dst_assets)

    # ------------------------------------------------------------------ #
    # Custom LaTeX math macros
    # ------------------------------------------------------------------ #
    def _latex_macro_error(self, message, source_name=None, source_text=None, pos=None):
        location = str(source_name) if source_name else "latex_macros"
        if source_text is not None and pos is not None:
            line, col = self._line_col(source_text, pos)
            location = f"{location}:{line}:{col}"
        raise LatexMacroError(f"{location}: {message}")

    @staticmethod
    def _line_col(text: str, pos: int):
        pos = max(0, min(pos, len(text)))
        line = text.count("\n", 0, pos) + 1
        last_newline = text.rfind("\n", 0, pos)
        return line, pos - last_newline

    def _normalize_latex_macros(self, raw_macros, source="latex_macros"):
        """Validate and normalize a latex_macros mapping.

        Supported forms:
          latex_macros:
            R: "\\mathbb{R}"                  # zero-argument shorthand
            esm:
              args: 1
              body: "\\left\\langle #1\\right\\rangle"
        """
        if not raw_macros:
            return {}
        if not isinstance(raw_macros, dict):
            self._latex_macro_error("expected a mapping of macro names to definitions", source)

        macros = {}
        for raw_name, spec in raw_macros.items():
            name = str(raw_name).strip()
            if name.startswith("\\"):
                name = name[1:]
            if not re.fullmatch(r"[A-Za-z]+", name):
                self._latex_macro_error(
                    f"invalid macro name {raw_name!r}; use only letters, with no arguments in the name",
                    source,
                )
            if name in self.RESERVED_LATEX_COMMANDS:
                self._latex_macro_error(f"cannot redefine reserved LaTeX command \\{name}", source)
            if name in macros:
                self._latex_macro_error(f"duplicate macro definition for \\{name}", source)

            if isinstance(spec, str):
                args = 0
                body = spec
            elif isinstance(spec, dict):
                if "args" not in spec or "body" not in spec:
                    self._latex_macro_error(
                        f"\\{name} must define both 'args' and 'body'",
                        source,
                    )
                args = spec["args"]
                body = spec["body"]
            else:
                self._latex_macro_error(
                    f"\\{name} must be a string or a mapping with 'args' and 'body'",
                    source,
                )

            if isinstance(args, bool) or not isinstance(args, int) or not (0 <= args <= 9):
                self._latex_macro_error(f"\\{name} args must be an integer from 0 to 9", source)
            if not isinstance(body, str):
                self._latex_macro_error(f"\\{name} body must be a string", source)
            self._validate_latex_macro_body(name, args, body, source)
            macros[name] = LatexMacro(name=name, args=args, body=body, source=str(source))

        return macros

    def _validate_latex_macro_body(self, name: str, args: int, body: str, source: str):
        i = 0
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                i += 2
                continue
            if body[i] == "#":
                if i + 1 >= len(body) or not body[i + 1].isdigit():
                    self._latex_macro_error(
                        f"\\{name} body has invalid parameter marker; use #1..#{args}",
                        source,
                    )
                index = int(body[i + 1])
                if index == 0 or index > args:
                    self._latex_macro_error(
                        f"\\{name} body references #{index}, but args is {args}",
                        source,
                    )
                i += 2
                continue
            i += 1

    def _latex_macros_for_metadata(self, metadata, path=None):
        global_macros = self._normalize_latex_macros(
            self.config.get("latex_macros", {}),
            "config.yaml:latex_macros",
        )
        local_macros = self._normalize_latex_macros(
            (metadata or {}).get("latex_macros", {}),
            f"{path}:latex_macros" if path else "frontmatter:latex_macros",
        )
        overlap = sorted(set(global_macros) & set(local_macros))
        if overlap:
            names = ", ".join(f"\\{name}" for name in overlap)
            self._latex_macro_error(
                f"duplicate macro definition across config and frontmatter: {names}",
                path or "latex_macros",
            )
        macros = {**global_macros, **local_macros}
        self._validate_latex_macro_cycles(macros, path or "latex_macros")
        return macros

    def _validate_latex_macro_cycles(self, macros, source):
        dependencies = {
            name: {
                dep for dep in self._latex_command_names(macro.body)
                if dep in macros
            }
            for name, macro in macros.items()
        }
        state = {}

        def visit(name, trail):
            mark = state.get(name)
            if mark == "done":
                return
            if mark == "visiting":
                start = trail.index(name)
                cycle = trail[start:]
                chain = " -> ".join(f"\\{item}" for item in cycle)
                self._latex_macro_error(f"recursive LaTeX macro definitions: {chain}", source)
            state[name] = "visiting"
            for dep in dependencies[name]:
                visit(dep, trail + [dep])
            state[name] = "done"

        for name in macros:
            visit(name, [name])

    @staticmethod
    def _latex_command_names(text: str):
        names = []
        i = 0
        while i < len(text):
            if text[i] == "\\" and i + 1 < len(text) and text[i + 1].isalpha():
                j = i + 2
                while j < len(text) and text[j].isalpha():
                    j += 1
                names.append(text[i + 1:j])
                i = j
            else:
                i += 1
        return names

    def _expand_latex_macros_in_metadata(self, metadata, macros, path=None):
        if not macros:
            return dict(metadata or {})

        expanded = dict(metadata or {})
        for key in ("title", "abstract", "category"):
            if isinstance(expanded.get(key), str):
                expanded[key] = self._expand_latex_macros_in_markdown(
                    expanded[key],
                    macros,
                    path,
                )

        for key in ("keywords", "tags"):
            if isinstance(expanded.get(key), list):
                expanded[key] = [
                    self._expand_latex_macros_in_markdown(item, macros, path)
                    if isinstance(item, str) else item
                    for item in expanded[key]
                ]

        authors = expanded.get("authors")
        if isinstance(authors, list):
            expanded_authors = []
            for author in authors:
                if not isinstance(author, dict):
                    expanded_authors.append(author)
                    continue
                author = dict(author)
                for key in ("name", "affiliation"):
                    if isinstance(author.get(key), str):
                        author[key] = self._expand_latex_macros_in_markdown(
                            author[key],
                            macros,
                            path,
                        )
                expanded_authors.append(author)
            expanded["authors"] = expanded_authors

        return expanded

    def _expand_latex_macros_in_markdown(self, content: str, macros, source_name=None) -> str:
        """Expand custom macros only inside LaTeX math regions.

        Markdown code fences and inline code spans are copied verbatim. This
        keeps commands in prose or code examples from being rewritten.
        """
        if not macros or not content:
            return content

        out = []
        i = 0
        while i < len(content):
            fence_end = self._fenced_code_block_end(content, i)
            if fence_end is not None:
                out.append(content[i:fence_end])
                i = fence_end
                continue

            inline_code_end = self._inline_code_span_end(content, i)
            if inline_code_end is not None:
                out.append(content[i:inline_code_end])
                i = inline_code_end
                continue

            math_span = self._math_span_at(content, i)
            if math_span is not None:
                open_start, inner_start, inner_end, close_end = math_span
                out.append(content[open_start:inner_start])
                inner = content[inner_start:inner_end]
                out.append(self._expand_latex_macro_text(
                    inner,
                    macros,
                    source_name=source_name,
                    source_text=content,
                    offset=inner_start,
                ))
                out.append(content[inner_end:close_end])
                i = close_end
                continue

            out.append(content[i])
            i += 1

        return "".join(out)

    def _expand_latex_macro_text(
        self,
        text: str,
        macros,
        source_name=None,
        source_text=None,
        offset=0,
        stack=(),
        depth=0,
    ) -> str:
        if depth > self.MAX_MACRO_EXPANSION_DEPTH:
            chain = " -> ".join(f"\\{name}" for name in stack) or "unknown"
            self._latex_macro_error(
                f"macro expansion exceeded depth limit near {chain}",
                source_name,
                source_text,
                offset,
            )

        out = []
        i = 0
        while i < len(text):
            if text[i] == "\\" and i + 1 < len(text) and text[i + 1].isalpha():
                j = i + 2
                while j < len(text) and text[j].isalpha():
                    j += 1
                name = text[i + 1:j]
                if name not in macros:
                    out.append(text[i:j])
                    i = j
                    continue

                if name in stack:
                    chain = " -> ".join(f"\\{item}" for item in (*stack, name))
                    self._latex_macro_error(
                        f"recursive LaTeX macro expansion: {chain}",
                        source_name,
                        source_text,
                        offset + i,
                    )

                macro = macros[name]
                args = []
                arg_pos = j
                for arg_index in range(1, macro.args + 1):
                    arg_pos = self._skip_latex_arg_space(text, arg_pos)
                    if arg_pos >= len(text) or text[arg_pos] != "{":
                        self._latex_macro_error(
                            f"\\{name} expects argument {arg_index} in braces",
                            source_name,
                            source_text,
                            offset + arg_pos,
                        )
                    arg_body, arg_pos = self._parse_latex_group(
                        text,
                        arg_pos,
                        source_name,
                        source_text,
                        offset,
                    )
                    args.append(self._expand_latex_macro_text(
                        arg_body,
                        macros,
                        source_name=source_name,
                        source_text=source_text,
                        offset=offset + arg_pos - len(arg_body) - 1,
                        stack=stack,
                        depth=depth + 1,
                    ))

                replacement = macro.body
                for index, value in enumerate(args, start=1):
                    replacement = replacement.replace(f"#{index}", value)
                out.append(self._expand_latex_macro_text(
                    replacement,
                    macros,
                    source_name=source_name,
                    source_text=source_text,
                    offset=offset + i,
                    stack=(*stack, name),
                    depth=depth + 1,
                ))
                i = arg_pos
                continue

            out.append(text[i])
            i += 1

        return "".join(out)

    @staticmethod
    def _skip_latex_arg_space(text: str, pos: int) -> int:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        return pos

    def _parse_latex_group(self, text: str, pos: int, source_name, source_text, offset):
        depth = 1
        i = pos + 1
        while i < len(text):
            if text[i] == "\\" and i + 1 < len(text):
                i += 2
                continue
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[pos + 1:i], i + 1
            i += 1
        self._latex_macro_error(
            "unclosed macro argument group",
            source_name,
            source_text,
            offset + pos,
        )

    def _fenced_code_block_end(self, text: str, pos: int):
        if pos != 0 and text[pos - 1] != "\n":
            return None
        line_end = text.find("\n", pos)
        if line_end == -1:
            line_end = len(text)
        line = text[pos:line_end]
        opener = re.match(r"[ \t]{0,3}(`{3,}|~{3,})", line)
        if not opener:
            return None

        marker = opener.group(1)
        marker_char = re.escape(marker[0])
        min_len = len(marker)
        closer = re.compile(rf"[ \t]{{0,3}}{marker_char}{{{min_len},}}[ \t]*$")
        scan = line_end + 1 if line_end < len(text) else len(text)
        while scan < len(text):
            next_end = text.find("\n", scan)
            if next_end == -1:
                next_end = len(text)
            if closer.match(text[scan:next_end]):
                return next_end + (1 if next_end < len(text) else 0)
            scan = next_end + 1
        return len(text)

    @staticmethod
    def _inline_code_span_end(text: str, pos: int):
        if text[pos] != "`":
            return None
        run_end = pos + 1
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        marker = text[pos:run_end]
        end = text.find(marker, run_end)
        if end == -1:
            return None
        return end + len(marker)

    def _math_span_at(self, text: str, pos: int):
        if text.startswith("$$", pos) and not self._is_escaped(text, pos):
            close = self._find_unescaped_token(text, "$$", pos + 2)
            if close is not None:
                return pos, pos + 2, close, close + 2

        if text.startswith("\\[", pos) and not self._is_escaped(text, pos):
            close = self._find_unescaped_token(text, "\\]", pos + 2)
            if close is not None:
                return pos, pos + 2, close, close + 2

        if text.startswith("\\(", pos) and not self._is_escaped(text, pos):
            close = self._find_unescaped_token(text, "\\)", pos + 2)
            if close is not None:
                return pos, pos + 2, close, close + 2

        env_span = self._math_environment_span_at(text, pos)
        if env_span is not None:
            return env_span

        if text[pos] == "$" and not self._is_escaped(text, pos):
            if pos + 1 < len(text) and text[pos + 1] == "$":
                return None
            close = self._find_inline_math_close(text, pos + 1)
            if close is not None:
                return pos, pos + 1, close, close + 1

        return None

    def _math_environment_span_at(self, text: str, pos: int):
        if not text.startswith("\\begin{", pos) or self._is_escaped(text, pos):
            return None
        begin = re.match(r"\\begin\{([A-Za-z*]+)\}", text[pos:])
        if not begin:
            return None
        env = begin.group(1)
        if env not in self.LATEX_MATH_ENVIRONMENTS:
            return None

        inner_start = pos + begin.end()
        env_re = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\}")
        depth = 1
        for match in env_re.finditer(text, inner_start):
            if self._is_escaped(text, match.start()):
                continue
            if match.group(1) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return pos, inner_start, match.start(), match.end()
        return None

    @staticmethod
    def _is_escaped(text: str, pos: int) -> bool:
        backslashes = 0
        i = pos - 1
        while i >= 0 and text[i] == "\\":
            backslashes += 1
            i -= 1
        return backslashes % 2 == 1

    def _find_unescaped_token(self, text: str, token: str, start: int):
        pos = text.find(token, start)
        while pos != -1:
            if not self._is_escaped(text, pos):
                return pos
            pos = text.find(token, pos + len(token))
        return None

    def _find_inline_math_close(self, text: str, start: int):
        pos = text.find("$", start)
        while pos != -1:
            if self._is_escaped(text, pos):
                pos = text.find("$", pos + 1)
                continue
            if (pos + 1 < len(text) and text[pos + 1] == "$") or (
                pos - 1 >= 0 and text[pos - 1] == "$"
            ):
                pos = text.find("$", pos + 1)
                continue
            return pos
        return None

    # ------------------------------------------------------------------ #
    # PDF generation — cache, LaTeX conversion, xelatex compilation
    # ------------------------------------------------------------------ #
    def _load_cache(self):
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_cache(self):
        self.cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _content_hash(self, path: Path) -> str:
        """Hash PDF inputs so template/config changes invalidate the cache."""
        digest = hashlib.sha256()
        for input_path in (
            path,
            self.root / "build.py",
            self.root / "config.yaml",
            self.template_dir / "article.tex",
        ):
            digest.update(input_path.read_bytes())
        return digest.hexdigest()

    def _should_rebuild_pdf(self, post: dict) -> bool:
        """Check whether the PDF needs to be rebuilt."""
        key = str(post["path"].relative_to(self.root))
        new_hash = self._content_hash(post["path"])
        cached = self._cache.get(key, {})
        pdf_path = self.root / ".tex_build" / f"{post['id']}.pdf"
        return (
            not isinstance(cached, dict)
            or cached.get("version") != CACHE_VERSION
            or cached.get("source_hash") != new_hash
            or not pdf_path.exists()
        )

    def _mark_pdf_built(self, post: dict) -> None:
        """Record a successful PDF build."""
        key = str(post["path"].relative_to(self.root))
        self._cache[key] = {
            "version": CACHE_VERSION,
            "source_hash": self._content_hash(post["path"]),
        }

    def _markdown_to_latex(self, content: str) -> str:
        """Convert markdown content to LaTeX body.

        Handles: headings, bold/italic, code blocks, math (pass-through),
        lists, blockquotes, links, images, horizontal rules.
        """
        lines = content.split("\n")
        out = []
        in_code = False
        code_lang = ""
        in_list = None   # 'ul' or 'ol'
        list_depth = 0
        in_quote = False
        i = 0

        while i < len(lines):
            line = lines[i]

            # Fenced code blocks
            fm = re.match(r"^(`{3,}|~{3,})(.*)$", line)
            if fm:
                if not in_code:
                    in_code = True
                    code_lang = fm.group(2).strip()
                    out.append("\\begin{codeverb}")
                    i += 1
                    continue
                else:
                    in_code = False
                    out.append("\\end{codeverb}")
                    i += 1
                    continue

            if in_code:
                # Escape LaTeX special chars in verbatim
                out.append(line)
                i += 1
                continue

            # Blank lines
            if not line.strip():
                if in_list and i + 1 < len(lines) and not re.match(r"^(\s*)[-*+]|\d+\.", lines[i + 1]):
                    # End list
                    out.append("\\end{" + in_list + "}")
                    in_list = None
                if in_quote and (i + 1 >= len(lines) or not lines[i + 1].startswith(">")):
                    out.append("\\end{quote}")
                    in_quote = False
                out.append("")
                i += 1
                continue

            # Math display blocks: $$...$$ → \[...\] (but skip if already \begin{...})
            if line.strip().startswith("$$"):
                math_lines = [line]
                if "$$" not in line or line.count("$$") < 2:
                    while i + 1 < len(lines):
                        i += 1
                        math_lines.append(lines[i])
                        if "$$" in lines[i]:
                            break
                math_block = "\n".join(math_lines)
                math_block = math_block.replace("$$", "", 1)
                math_block = re.sub(r"\$\$$", "", math_block)
                inner = math_block.strip()
                # If inner already has \begin{equation}/\begin{align}, use as-is
                if re.match(r"\\begin\{(equation|align)", inner):
                    out.append(inner)
                else:
                    out.append("\\[")
                    out.append(inner)
                    out.append("\\]")
                i += 1
                continue

            # Native LaTeX math environments are kept raw for PDF output.
            env_m = re.match(r"^\\begin\{([A-Za-z*]+)\}", line.strip())
            if env_m and env_m.group(1) in self.LATEX_MATH_ENVIRONMENTS:
                env = env_m.group(1)
                math_lines = [line]
                while i + 1 < len(lines):
                    i += 1
                    math_lines.append(lines[i])
                    if re.search(r"\\end\{" + re.escape(env) + r"\}", lines[i]):
                        break
                out.append("\n".join(math_lines))
                i += 1
                continue

            if line.strip() == "---" or line.strip() == "***":
                out.append("\\vspace{4pt}")
                out.append("\\rule{\\textwidth}{0.5pt}")
                out.append("\\vspace{4pt}")
                i += 1
                continue

            # Headings — protect math before escaping
            hm = re.match(r"^(#{1,6})\s+(.+)$", line)
            if hm:
                level = len(hm.group(1))
                title = hm.group(2).strip()
                # Protect math spans from escaping
                math_spans_h = []
                def save_math_h(m):
                    math_spans_h.append(m.group(0))
                    return f"<MATHH{len(math_spans_h)-1}>"
                title = re.sub(r"\$[^$]+\$", save_math_h, title)
                title = re.sub(r"\\\(.+?\\\)", save_math_h, title)
                title = self._latex_escape(title)
                for math_index, math in enumerate(math_spans_h):
                    title = title.replace(f"<MATHH{math_index}>", math)
                # The PDF title comes from frontmatter, so Markdown H2 is the
                # natural top-level section inside an article body.
                if level <= 2:
                    out.append(f"\\section{{{title}}}")
                elif level == 3:
                    out.append(f"\\subsection{{{title}}}")
                elif level == 4:
                    out.append(f"\\subsubsection{{{title}}}")
                else:
                    out.append(f"\\paragraph{{{title}}}")
                i += 1
                continue

            # Blockquotes
            if line.startswith(">"):
                if not in_quote:
                    out.append("\\begin{quote}")
                    in_quote = True
                text = re.sub(r"^>\s?", "", line)
                text = self._latex_inline(text)
                out.append(text)
                i += 1
                continue
            elif in_quote:
                out.append("\\end{quote}")
                in_quote = False

            # Unordered list
            ulm = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
            if ulm:
                if in_list != "itemize":
                    if in_list:
                        out.append("\\end{" + in_list + "}")
                    out.append("\\begin{itemize}")
                    in_list = "itemize"
                text = self._latex_inline(ulm.group(2))
                out.append(f"\\item {text}")
                i += 1
                continue

            # Ordered list
            olm = re.match(r"^(\s*)\d+\.\s+(.+)$", line)
            if olm:
                if in_list != "enumerate":
                    if in_list:
                        out.append("\\end{" + in_list + "}")
                    out.append("\\begin{enumerate}")
                    in_list = "enumerate"
                text = self._latex_inline(olm.group(2))
                out.append(f"\\item {text}")
                i += 1
                continue

            # Regular paragraph
            if in_list:
                out.append("\\end{" + in_list + "}")
                in_list = None

            text = self._latex_inline(line)
            if text.strip():
                out.append(text)
            else:
                out.append("")
            i += 1

        # Close any open environments
        if in_code:
            out.append("\\end{codeverb}")
        if in_list:
            out.append("\\end{" + in_list + "}")
        if in_quote:
            out.append("\\end{quote}")

        return "\n".join(out)

    def _latex_inline(self, text: str) -> str:
        """Convert inline markdown to LaTeX."""
        text, math_spans = self._protect_latex_math_spans(text)
        raw_parts = []

        def protect_raw(value):
            token = f"@@LATEXRAW{len(raw_parts)}@@"
            raw_parts.append(value)
            return token

        # Images ![alt](path) — MUST be before links
        def replace_img(m):
            alt = m.group(1)
            path = m.group(2)
            # Parse width specifier: |width=60% or |width=300px at the end
            width = "0.88\\linewidth"
            wm = re.search(r'\|width=([^|]+)$', alt)
            if wm:
                w = wm.group(1).strip()
                alt = alt[:wm.start()]
                if w.endswith('%'):
                    try:
                        fraction = max(0.05, min(float(w[:-1]) / 100, 1.0))
                    except ValueError:
                        fraction = 0.88
                    width = f"{fraction:.3g}\\linewidth"
                elif re.fullmatch(r"\d+(?:\.\d+)?(?:pt|mm|cm|in|em|ex)", w):
                    width = w
            # Strip fig:key| or tbl:key| prefix from caption
            label = ""
            label_m = re.match(r'^((?:fig|tbl):[a-zA-Z0-9_-]+)\|(.*)$', alt)
            if label_m:
                label = f"\n\\label{{{label_m.group(1)}}}"
                caption = label_m.group(2)
            else:
                caption = alt
            caption = self._latex_escape(caption)
            path = self._latex_detokenize(path)
            return protect_raw(
                "\\begin{figure}[H]\n"
                "\\centering\n"
                f"\\includegraphics[width={width},max width=\\linewidth]{{\\detokenize{{{path}}}}}\n"
                f"\\caption{{{caption}}}{label}\n"
                "\\end{figure}"
            )
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_img, text)

        # Links [text](url)
        def replace_link(m):
            label = m.group(1)
            url = m.group(2)
            safe_url = self._latex_url_arg(url)
            if label.strip() == url.strip():
                return protect_raw(f"\\url{{{safe_url}}}")
            return protect_raw(f"\\href{{{safe_url}}}{{{self._latex_escape(label)}}}")
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, text)

        # Cross-references
        text = re.sub(
            r"\[@eq:([^\]]+)\]",
            lambda m: protect_raw(f"\\textsf{{公式 \\ref{{eq:{m.group(1)}}}}}"),
            text,
        )
        text = re.sub(
            r"\[@fig:([^\]]+)\]",
            lambda m: protect_raw(f"\\textsf{{图 \\ref{{fig:{m.group(1)}}}}}"),
            text,
        )
        text = re.sub(
            r"\[@tbl:([^\]]+)\]",
            lambda m: protect_raw(f"\\textsf{{表 \\ref{{tbl:{m.group(1)}}}}}"),
            text,
        )
        text = re.sub(
            r"\\textsuperscript\{\[[0-9,]+\]\}",
            lambda m: protect_raw(m.group(0)),
            text,
        )

        # Bold / italic / inline code become protected LaTeX fragments.
        text = re.sub(
            r"\*\*(.+?)\*\*",
            lambda m: protect_raw(f"\\textbf{{{self._latex_escape(m.group(1))}}}"),
            text,
        )
        text = re.sub(
            r"(?<!\*)\*([^*]+)\*(?!\*)",
            lambda m: protect_raw(f"\\emph{{{self._latex_escape(m.group(1))}}}"),
            text,
        )
        text = re.sub(
            r"`([^`]+)`",
            lambda m: protect_raw(f"\\texttt{{{self._latex_escape(m.group(1))}}}"),
            text,
        )

        text = self._latex_escape(text)

        # Restore protected LaTeX fragments, then math placeholders that may
        # occur inside captions or link labels.
        for i in range(len(raw_parts) - 1, -1, -1):
            text = text.replace(f"@@LATEXRAW{i}@@", raw_parts[i])
        for i, math in enumerate(math_spans):
            text = text.replace(f"@@LATEXMATH{i}@@", math)

        return text

    def _protect_latex_math_spans(self, text: str):
        math_spans = []
        out = []
        i = 0
        while i < len(text):
            span = self._math_span_at(text, i)
            if span is not None:
                start, _, _, end = span
                token = f"@@LATEXMATH{len(math_spans)}@@"
                math_spans.append(text[start:end])
                out.append(token)
                i = end
                continue
            out.append(text[i])
            i += 1
        return "".join(out), math_spans

    @staticmethod
    def _latex_escape(text: str) -> str:
        """Escape LaTeX special characters in plain text."""
        replacements = {
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
        return "".join(replacements.get(ch, ch) for ch in str(text))

    @staticmethod
    def _latex_url_arg(url: str) -> str:
        return (
            str(url)
            .replace("\\", "/")
            .replace("%", r"\%")
            .replace("#", r"\#")
            .replace("{", r"\{")
            .replace("}", r"\}")
        )

    @staticmethod
    def _latex_detokenize(text: str) -> str:
        return str(text).replace("{", r"\{").replace("}", r"\}")

    def _compile_pdf(self, tex_path: Path, out_dir: Path) -> bool:
        """Run xelatex twice to compile a PDF. Returns True on success."""
        out_dir.mkdir(parents=True, exist_ok=True)
        jobname = tex_path.stem
        pdf_path = out_dir / f"{jobname}.pdf"
        command = [
            "xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory", str(out_dir),
            "-jobname", jobname,
            str(tex_path),
        ]

        for run in (1, 2):
            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.root),
                    timeout=60,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                print(f"\n  [PDF] xelatex could not run: {exc}")
                return False
            if result.returncode != 0:
                break

        ok = result.returncode == 0 and pdf_path.exists() and pdf_path.stat().st_size > 0
        if not ok:
            log_path = out_dir / f"{jobname}.log"
            tail = ""
            if log_path.exists():
                lines = log_path.read_text(errors="replace").splitlines()
                tail = "\n".join(lines[-20:])
            print(f"\n  [PDF] xelatex failed:\n{tail}")
        # Keep failed-build logs for diagnosis.
        cleanup_exts = (".aux", ".out", ".toc", ".log") if ok else (".aux", ".out", ".toc")
        for ext in cleanup_exts:
            p = out_dir / f"{jobname}{ext}"
            if p.exists():
                p.unlink()
        return ok

    def _copy_pdf_to_output(self, post: dict) -> None:
        """Copy cached PDF from .tex_build to output directory."""
        post_id = post["id"]
        pdf_src = self.root / ".tex_build" / f"{post_id}.pdf"
        pdf_dst = self.output_dir / post["url"].replace(".html", ".pdf")
        post["pdf_available"] = False
        if pdf_src.exists():
            pdf_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf_src, pdf_dst)
            post["pdf_available"] = True

    def _build_preamble(self) -> str:
        """Build LaTeX preamble with config values baked in."""
        jname = self.config.get("journal", {}).get("name", "Research Blog")
        subtitle = self.config.get("site_subtitle", "")
        # Escape LaTeX specials in config strings
        jname = jname.replace("&", "\\&").replace("%", "\\%").replace("#", "\\#")
        subtitle = subtitle.replace("&", "\\&").replace("%", "\\%").replace("#", "\\#")

        return f"""\\documentclass[10pt,a4paper]{{ctexart}}

% ---- Fonts ----
\\usepackage{{libertinus}}
% ctexart handles CJK fonts automatically on macOS

% ---- Geometry ----
\\usepackage[
  a4paper,
  top=22mm,bottom=24mm,
  left=23mm,right=23mm,
  headsep=7mm,footskip=10mm,
  includeheadfoot
]{{geometry}}

% ---- Spacing ----
\\linespread{{1.0}}
\\setlength{{\\parskip}}{{0.34em plus 0.08em minus 0.06em}}
\\setlength{{\\parindent}}{{1.2em}}
\\setlength{{\\emergencystretch}}{{3em}}
\\raggedbottom
\\sloppy
\\setlength{{\\abovedisplayskip}}{{7pt plus 2pt minus 2pt}}
\\setlength{{\\belowdisplayskip}}{{7pt plus 2pt minus 2pt}}
\\setlength{{\\abovedisplayshortskip}}{{2pt plus 1pt}}
\\setlength{{\\belowdisplayshortskip}}{{4pt plus 1pt minus 1pt}}
\\usepackage{{enumitem}}
\\setlist{{topsep=2pt,itemsep=1pt,parsep=0pt,leftmargin=*}}
\\usepackage{{microtype}}

% ---- Colors ----
\\usepackage{{xcolor}}
\\definecolor{{accent}}{{HTML}}{{8B0000}}
\\definecolor{{dark}}{{HTML}}{{1A1A1A}}
\\definecolor{{muted}}{{HTML}}{{555555}}

% ---- Hyperlinks ----
\\usepackage{{xurl}}
\\usepackage{{hyperref}}
\\hypersetup{{colorlinks=true,linkcolor=accent,urlcolor=accent,citecolor=accent,breaklinks=true}}
\\urlstyle{{same}}
\\Urlmuskip=0mu plus 2mu

% ---- Headers / Footers ----
\\usepackage{{fancyhdr}}
\\pagestyle{{fancy}}
\\fancyhf{{}}
\\fancyhead[L]{{\\small\\textsf{{\\color{{muted}}{jname}}}}}
\\fancyhead[R]{{\\small\\textsf{{\\color{{muted}}Vol.\\ I \\ No.\\ 1}}}}
\\fancyfoot[C]{{\\small\\textsf{{\\color{{muted}}\\thepage}}}}
\\renewcommand{{\\headrulewidth}}{{0.4pt}}
\\renewcommand{{\\footrulewidth}}{{0pt}}
\\setlength{{\\headheight}}{{14pt}}

% ---- Code blocks ----
\\usepackage{{fvextra}}
\\fvset{{fontsize=\\small,frame=single,framerule=0.35pt,framesep=5pt,breaklines=true,breakanywhere=true}}
\\DefineVerbatimEnvironment{{codeverb}}{{Verbatim}}{{}}

% ---- Graphics ----
\\usepackage{{graphicx}}
\\usepackage{{float}}
\\usepackage[export]{{adjustbox}}
\\graphicspath{{ {{content/}} }}

% ---- Math ----
\\usepackage{{amsmath}}
\\allowdisplaybreaks
\\usepackage{{unicode-math}}
\\setmathfont{{latinmodern-math.otf}}

% ---- Captions ----
\\usepackage{{caption}}
\\captionsetup{{font={{small,sf}},labelfont={{bf,color=accent}},labelsep=period,skip=4pt}}

% ---- Abstract box ----
\\usepackage[most]{{tcolorbox}}
\\newtcolorbox{{paperabstract}}{{enhanced,breakable,colback=black!2,colframe=black!18,
  boxrule=0.35pt,arc=1.5pt,left=7pt,right=7pt,top=6pt,bottom=6pt}}

% ---- Section headings ----
\\usepackage{{titlesec}}
\\titleformat{{\\section}}{{\\large\\bfseries\\color{{dark}}}}{{\\thesection}}{{0.65em}}{{}}[\\vspace{{-1pt}}\\rule{{\\textwidth}}{{0.35pt}}]
\\titleformat{{\\subsection}}{{\\normalsize\\bfseries\\color{{dark}}}}{{\\thesubsection}}{{0.6em}}{{}}
\\titleformat{{\\subsubsection}}{{\\normalsize\\bfseries\\color{{dark}}}}{{\\thesubsubsection}}{{0.6em}}{{}}
\\titlespacing{{\\section}}{{0pt}}{{13pt plus 3pt}}{{6pt plus 2pt}}
\\titlespacing{{\\subsection}}{{0pt}}{{10pt plus 2pt}}{{4pt plus 2pt}}
\\titlespacing{{\\subsubsection}}{{0pt}}{{8pt plus 2pt}}{{3pt plus 2pt}}

% ---- Footnotes ----
\\renewcommand{{\\footnotesize}}{{\\scriptsize}}"""

    def _build_pdf(self, post: dict) -> None:
        """Convert post to LaTeX, compile PDF, copy to output."""
        tex_dir = self.root / ".tex_build"
        tex_dir.mkdir(exist_ok=True)

        post_id = post["id"]
        tex_path = tex_dir / f"{post_id}.tex"

        # Prepare template variables
        authors = post.get("authors", [])
        affiliations = []
        for idx, a in enumerate(authors):
            if a.get("affiliation"):
                affiliations.append({"num": idx + 1, "text": a["affiliation"]})

        abstract = post.get("abstract", "")
        keywords = post.get("keywords", [])

        # Get raw markdown content (strip frontmatter)
        import frontmatter as fm
        raw = fm.load(str(post["path"]))
        macros = self._latex_macros_for_metadata(raw.metadata, post["path"])

        # Parse bibliography for LaTeX
        raw_bib = post.get("bibliography", [])
        bib_entries = self._normalize_bibliography(raw_bib)
        bib_map = {key: i for i, (key, _) in enumerate(bib_entries, start=1)}

        # Replace [@key] citations with LaTeX superscript refs
        raw_content = self._expand_latex_macros_in_markdown(
            raw.content,
            macros,
            post["path"],
        )
        raw_content = self._replace_citations_latex(raw_content, bib_map)

        # Native LaTeX equation environments compile correctly as-is.
        body = self._markdown_to_latex(raw_content)

        # Append bibliography if present
        if bib_entries:
            body += "\n\n\\section*{References}\n"
            body += "\\begin{enumerate}[leftmargin=*,nosep]\n"
            for key, text in bib_entries:
                safe_text = text.replace("&", "\\&").replace("%", "\\%").replace("#", "\\#").replace("_", "\\_")
                body += f"  \\item {safe_text}\n"
            body += "\\end{enumerate}\n"

        # Build LaTeX preamble (static, with config baked in)
        preamble = self._build_preamble()

        # Render LaTeX template
        tex_tmpl = self.jinja.get_template("article.tex")
        tex_content = tex_tmpl.render(
            preamble=preamble,
            journal_name=self._latex_escape(self.config.get("journal", {}).get("name", "Blog")),
            author_name=self._latex_escape(self.config.get("author", "")),
            title=self._latex_inline(post.get("title", "")),
            authors=[
                {**author, "name": self._latex_escape(author.get("name", ""))}
                for author in authors
            ],
            affiliations=[
                {**affiliation, "text": self._latex_escape(affiliation["text"])}
                for affiliation in affiliations
            ],
            date=post.get("date").strftime("%Y-%m-%d") if post.get("date") else "",
            abstract=self._latex_inline(abstract),
            keywords=[self._latex_inline(keyword) for keyword in keywords],
            category=self._latex_escape(post.get("category", "")),
            doi=self._latex_escape(post.get("doi", "")),
            body=body,
        )

        tex_path.write_text(tex_content, encoding="utf-8")

        # Compile
        print(f"  [PDF] Compiling {post['id']} ... ", end="", flush=True)
        cached_pdf = tex_dir / f"{post_id}.pdf"
        if cached_pdf.exists():
            cached_pdf.unlink()
        ok = self._compile_pdf(tex_path, tex_dir)
        post["pdf_available"] = False
        if ok:
            self._mark_pdf_built(post)
            pdf_src = tex_dir / f"{post_id}.pdf"
            pdf_dst = self.output_dir / post["url"].replace(".html", ".pdf")
            pdf_dst.parent.mkdir(parents=True, exist_ok=True)
            if pdf_src.exists():
                shutil.copy2(pdf_src, pdf_dst)
                post["pdf_available"] = True
                size_kb = pdf_dst.stat().st_size // 1024
                print(f"✓  ({size_kb} KB)")
            else:
                print("✗  (PDF not generated)")
        else:
            print("✗")

    # ------------------------------------------------------------------ #
    # Bibliography
    # ------------------------------------------------------------------ #
    def _normalize_bibliography(self, bib):
        """Convert bibliography to list of (key, text) tuples.

        Supports three formats:
          1. Dict:  {key: text, ...}           — recommended, keys are explicit
          2. List of strings: ["text", ...]     — legacy, auto-keys ref1..refN
          3. List of dicts: [{key: ..., text: ...}]  — alternative
        """
        if not bib:
            return []
        result = []
        if isinstance(bib, dict):
            for key, text in bib.items():
                result.append((str(key), str(text)))
        elif isinstance(bib, list):
            for i, item in enumerate(bib, start=1):
                if isinstance(item, dict) and "key" in item:
                    result.append((str(item["key"]), str(item.get("text", ""))))
                elif isinstance(item, str):
                    result.append((f"ref{i}", item))
                else:
                    result.append((f"ref{i}", str(item)))
        return result

    @staticmethod
    def _preprocess_citations(content, bib_map):
        """Replace [@key] and [@key1; @key2] with [^N] footnote refs."""
        def repl(match):
            inner = match.group(1)
            keys = [k.strip().lstrip("@") for k in inner.split(";")]
            refs = []
            for k in keys:
                if k in bib_map:
                    refs.append(f"[^{bib_map[k]}]")
                else:
                    refs.append(f"[@{k}]")  # keep unknown keys as-is
            return "".join(refs)
        return re.sub(r"\[@([a-zA-Z0-9_\-; @]+)\]", repl, content)

    @staticmethod
    def _replace_citations_latex(content, bib_map):
        """Replace [@key] and [@key1; @key2] with LaTeX superscript refs."""
        def repl(match):
            inner = match.group(1)
            keys = [k.strip().lstrip("@") for k in inner.split(";")]
            nums = []
            for k in keys:
                if k in bib_map:
                    nums.append(str(bib_map[k]))
            if nums:
                return f"\\textsuperscript{{[{','.join(nums)}]}}"
            return match.group(0)
        return re.sub(r"\[@([a-zA-Z0-9_\-; @]+)\]", repl, content)

    @staticmethod
    def _preprocess_equations(content):
        """Pre-process equation blocks before markdown conversion.

        - Converts equation/align environments to display math for arithmatex.
        - Extracts \\label{eq:key} → builds label-to-number map.
        - Adds \\tag{N} for KaTeX equation numbering.
        - Inserts anchor <a id="eq:key"></a> before labeled equations.
        - Does NOT touch blocks already inside $$ or \\[...\\].

        Returns: (processed_content, eq_labels: dict)
        """
        eq_labels = {}   # label → number
        eq_counter = 0

        def replace_eq(match):
            nonlocal eq_counter
            full = match.group(0)
            body = match.group(2)

            # Skip if already inside display-math delimiters
            before_start = max(0, match.start() - 20)
            before = content[before_start:match.start()]
            if '$$' in before:
                return full

            eq_counter += 1

            # Pull out \label{eq:key}
            label_m = re.search(r'\\label\{eq:([a-zA-Z0-9_-]+)\}', body)
            label_key = None
            if label_m:
                label_key = label_m.group(1)
                eq_labels[label_key] = eq_counter
                body = body[:label_m.start()] + body[label_m.end():]

            # Build anchor for labeled equations (with blank lines for paragraph breaks)
            anchor = f'\n\n<a id="eq:{label_key}"></a>\n\n' if label_key else '\n\n'

            return (
                f'{anchor}'
                f'$$\n'
                f'{body.strip()}\n'
                f'\\tag{{{eq_counter}}}\n'
                f'$$'
            )

        content = re.sub(
            r'\\begin\{(equation|align)\}(.*?)\\end\{\1\}',
            replace_eq,
            content,
            flags=re.DOTALL,
        )

        return content, eq_labels

    @staticmethod
    def _process_numbered_refs(body, eq_labels=None):
        """Post-process HTML: auto-number figures/tables/equations and resolve refs.

        Figure syntax in markdown:  ![fig:alias|Caption text](path/to/img.png)
        Table syntax in markdown:    [@tbl:alias|Caption text]  (line immediately before the table)
        Equation syntax:            \\begin{equation}\\label{eq:key} ... \\end{equation}
        Reference in text:          [@fig:alias]  /  [@tbl:alias]  /  [@eq:key]
        """
        if eq_labels is None:
            eq_labels = {}

        fig_counter = 0
        tbl_counter = 0
        fig_aliases = {}
        tbl_aliases = {}

        # Pass 1: Numbered figures — <img alt="fig:key|caption" ...> → <figure>
        def replace_fig(match):
            nonlocal fig_counter
            key = match.group(1)
            caption = match.group(2)
            rest = match.group(3)
            fig_counter += 1
            fig_aliases[key] = fig_counter
            # Parse width specifier: |width=X% or |width=Xpx
            width_style = ""
            wm = re.search(r'\|width=([^"]+)$', caption)
            if wm:
                w = wm.group(1).strip()
                caption = caption[:wm.start()]
                width_style = f' style="width: {w}"'
            src_m = re.search(r'src="([^"]*)"', rest)
            src = src_m.group(1) if src_m else ""
            return (
                f'<figure id="fig:{key}" class="numbered-fig">\n'
                f'  <img src="{src}" alt="{caption}"{width_style}>\n'
                f'  <figcaption>图 {fig_counter}：{caption}</figcaption>\n'
                f'</figure>'
            )

        body = re.sub(
            r'<p>\s*<img\s+alt="fig:([a-zA-Z0-9_-]+)\|([^"]*)"([^>]*/?)\s*>\s*</p>',
            replace_fig,
            body,
        )

        # Pass 2: Numbered tables — <p>[@tbl:key|caption]</p><table>...</table> → <figure>
        def replace_tbl(match):
            nonlocal tbl_counter
            key = match.group(1)
            caption = match.group(2)
            table = match.group(3)
            tbl_counter += 1
            tbl_aliases[key] = tbl_counter
            return (
                f'<figure id="tbl:{key}" class="numbered-tbl">\n'
                f'  <figcaption>表 {tbl_counter}：{caption}</figcaption>\n'
                f'  {table}\n'
                f'</figure>'
            )

        body = re.sub(
            r'<p>\[@tbl:([a-zA-Z0-9_-]+)\|([^\]]+)\]</p>\s*(<table>.*?</table>)',
            replace_tbl,
            body,
            flags=re.DOTALL,
        )

        # Pass 3: Resolve [@fig:key], [@tbl:key], [@eq:key] to numbered links
        def replace_ref(match):
            prefix = match.group(1)
            key = match.group(2)
            if prefix == "fig" and key in fig_aliases:
                return f'<a href="#fig:{key}" class="xref">图 {fig_aliases[key]}</a>'
            if prefix == "tbl" and key in tbl_aliases:
                return f'<a href="#tbl:{key}" class="xref">表 {tbl_aliases[key]}</a>'
            if prefix == "eq" and key in eq_labels:
                return f'<a href="#eq:{key}" class="xref">公式 {eq_labels[key]}</a>'
            return match.group(0)

        body = re.sub(r'\[@(fig|tbl|eq):([a-zA-Z0-9_-]+)\]', replace_ref, body)

        return body

    # ------------------------------------------------------------------ #
    # Zhihu Markdown export
    # ------------------------------------------------------------------ #
    @staticmethod
    def _preprocess_equations_for_markdown(content):
        """Convert LaTeX equation/align environments to plain display math.

        This is for platforms such as Zhihu that accept normal Markdown plus
        $$...$$ math, but do not understand the blog's custom equation labels.

        Returns: (processed_content, eq_labels: dict)
        """
        eq_labels = {}
        eq_counter = 0

        def replace_eq(match):
            nonlocal eq_counter
            env = match.group(1)
            body = match.group(2).strip()

            eq_counter += 1

            label_m = re.search(r'\\label\{eq:([a-zA-Z0-9_-]+)\}', body)
            if label_m:
                eq_labels[label_m.group(1)] = eq_counter
                body = body[:label_m.start()] + body[label_m.end():]
                body = body.strip()

            if env == "align":
                body = "\\begin{aligned}\n" + body + "\n\\end{aligned}"

            return f"\n\n$$\n{body}\n\\tag{{{eq_counter}}}\n$$\n\n"

        content = re.sub(
            r'\\begin\{(equation|align)\}(.*?)\\end\{\1\}',
            replace_eq,
            content,
            flags=re.DOTALL,
        )
        return content, eq_labels

    @staticmethod
    def _replace_citations_plain_markdown(content, bib_map):
        """Replace [@key] and [@key1; @key2] with ordinary [N] text."""
        def repl(match):
            inner = match.group(1)
            keys = [k.strip().lstrip("@") for k in inner.split(";")]
            nums = [str(bib_map[k]) for k in keys if k in bib_map]
            if nums:
                return "".join(f"[{n}]" for n in nums)
            return match.group(0)

        return re.sub(r"\[@([a-zA-Z0-9_\-; @]+)\]", repl, content)

    @staticmethod
    def _strip_width_from_alt(alt):
        """Remove trailing |width=... from image alt text."""
        width_m = re.search(r"\|width=[^|]+$", alt)
        if width_m:
            return alt[:width_m.start()]
        return alt

    def _zhihu_asset_path(self, path_text):
        """Rewrite local asset paths relative to public/zhihu/*.md."""
        if re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|/|#)", path_text):
            return path_text
        if path_text.startswith("../"):
            return path_text
        return "../" + path_text

    def _process_numbered_refs_markdown(self, content, eq_labels=None):
        """Resolve blog-specific figure/table/equation references to text."""
        if eq_labels is None:
            eq_labels = {}

        fig_counter = 0
        tbl_counter = 0
        fig_aliases = {}
        tbl_aliases = {}

        def replace_fig(match):
            nonlocal fig_counter
            alt = match.group(1)
            path = self._zhihu_asset_path(match.group(2))

            fig_m = re.match(r"fig:([a-zA-Z0-9_-]+)\|(.*)$", alt)
            if not fig_m:
                plain_alt = self._strip_width_from_alt(alt)
                return f"![{plain_alt}]({path})"

            key = fig_m.group(1)
            caption = self._strip_width_from_alt(fig_m.group(2)).strip()
            fig_counter += 1
            fig_aliases[key] = fig_counter
            return f"![图 {fig_counter}：{caption}]({path})\n\n图 {fig_counter}：{caption}"

        content = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            replace_fig,
            content,
        )

        def replace_tbl_marker(match):
            nonlocal tbl_counter
            key = match.group(1)
            caption = match.group(2).strip()
            tbl_counter += 1
            tbl_aliases[key] = tbl_counter
            return f"表 {tbl_counter}：{caption}\n"

        content = re.sub(
            r"^\s*\[@tbl:([a-zA-Z0-9_-]+)\|([^\]]+)\]\s*$",
            replace_tbl_marker,
            content,
            flags=re.MULTILINE,
        )

        def replace_ref(match):
            prefix = match.group(1)
            key = match.group(2)
            if prefix == "fig" and key in fig_aliases:
                return f"图 {fig_aliases[key]}"
            if prefix == "tbl" and key in tbl_aliases:
                return f"表 {tbl_aliases[key]}"
            if prefix == "eq" and key in eq_labels:
                return f"公式 {eq_labels[key]}"
            return match.group(0)

        return re.sub(r"\[@(fig|tbl|eq):([a-zA-Z0-9_-]+)\]", replace_ref, content)

    def _post_to_zhihu_markdown(self, post):
        """Compile one post to portable Markdown for Zhihu import."""
        raw = frontmatter.load(str(post["path"]))
        macros = self._latex_macros_for_metadata(raw.metadata, post["path"])
        metadata = self._expand_latex_macros_in_metadata(raw.metadata, macros, post["path"])

        bib_entries = self._normalize_bibliography(metadata.get("bibliography", []))
        bib_map = {key: i for i, (key, _) in enumerate(bib_entries, start=1)}

        content = self._expand_latex_macros_in_markdown(
            raw.content,
            macros,
            post["path"],
        ).strip()
        content = self._replace_citations_plain_markdown(content, bib_map)
        content, eq_labels = self._preprocess_equations_for_markdown(content)
        content = self._process_numbered_refs_markdown(content, eq_labels)

        title = metadata.get("title", post.get("title", "Untitled"))
        parts = [f"# {title}"]

        abstract = metadata.get("abstract", "")
        if abstract:
            parts.append(f"> {abstract}")

        parts.append(content)

        if bib_entries:
            refs = ["## 参考文献"]
            for key, text in bib_entries:
                refs.append(f"[{bib_map[key]}] {text}")
            parts.append("\n".join(refs))

        text = "\n\n".join(part.strip() for part in parts if part and part.strip())
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.rstrip() + "\n"

    def _build_zhihu_markdown(self, post):
        out_dir = self.output_dir / "zhihu"
        self._ensure_dir(out_dir)
        filename = f"{post.get('slug') or post['id']}.md"
        out = out_dir / filename
        out.write_text(self._post_to_zhihu_markdown(post), encoding="utf-8")
        print(f"  [ZH]  {out.relative_to(self.output_dir)}")

    def _parse_markdown(self, path: Path):
        post = frontmatter.load(str(path))
        macros = self._latex_macros_for_metadata(post.metadata, path)
        metadata = self._expand_latex_macros_in_metadata(post.metadata, macros, path)

        raw_bib = metadata.get("bibliography", [])
        bib_entries = self._normalize_bibliography(raw_bib)
        bib_map = {key: i for i, (key, _) in enumerate(bib_entries, start=1)}

        # Preprocess: expand custom math macros, then [@key] → [^N]
        content = self._expand_latex_macros_in_markdown(post.content, macros, path)
        content = self._preprocess_citations(content, bib_map)

        # Preprocess: number equations and build label→number map
        content, eq_labels = self._preprocess_equations(content)

        # Inject bibliography as footnote definitions
        if bib_entries:
            content += "\n\n"
            for key, text in bib_entries:
                content += f"[^{bib_map[key]}]: {text}\n"

        body = self.md.convert(content)
        body = self._process_numbered_refs(body, eq_labels)
        toc = self.md.toc if hasattr(self.md, "toc") else ""
        self.md.reset()

        meta = {
            **metadata,
            "title": metadata.get("title", "Untitled"),
            "date": metadata.get("date"),
            "updated": metadata.get("updated"),
            "authors": metadata.get("authors", []),
            "abstract": metadata.get("abstract", ""),
            "keywords": metadata.get("keywords", []),
            "tags": metadata.get("tags", []),
            "category": metadata.get("category", "Uncategorized"),
            "doi": metadata.get("doi", ""),
            "bibliography": metadata.get("bibliography", []),
            "banner": metadata.get("banner", ""),
            "draft": metadata.get("draft", False),
            "id": self._article_id(path),
            "slug": metadata.get("slug", self._slugify(metadata.get("title", "untitled"))),
            "path": path,
            "body": body,
            "toc": toc,
            "pdf_available": False,
        }

        if meta["date"] and isinstance(meta["date"], str):
            try:
                meta["date"] = datetime.strptime(meta["date"], "%Y-%m-%d")
            except ValueError:
                pass

        return meta

    # ------------------------------------------------------------------ #
    # Loaders
    # ------------------------------------------------------------------ #
    def _load_posts(self):
        posts_dir = self.content_dir / "posts"
        if not posts_dir.exists():
            return

        for path in sorted(posts_dir.rglob("*.md")):
            meta = self._parse_markdown(path)
            if meta["draft"]:
                continue
            meta["url"] = f"posts/{meta['id']}.html"
            self.posts.append(meta)
            # Build PDF if source changed (skip in dev mode)
            if not self.skip_pdf:
                if self._should_rebuild_pdf(meta):
                    self._build_pdf(meta)
                # Always copy cached PDF to output (public/ is wiped each build)
                self._copy_pdf_to_output(meta)

        self.posts.sort(key=lambda x: x["date"] or datetime.min, reverse=True)

        for p in self.posts:
            for t in p["tags"]:
                self.tags[t].append(p)
            cat = p["category"]
            self.categories[cat].append(p)
            if p["date"]:
                ym = p["date"].strftime("%Y-%m")
                self.archives[ym].append(p)

    def _load_pages(self):
        pages_dir = self.content_dir / "pages"
        if not pages_dir.exists():
            return

        for path in sorted(pages_dir.rglob("*.md")):
            meta = self._parse_markdown(path)
            meta["url"] = f"pages/{meta['id']}.html"
            self.pages.append(meta)

    # ------------------------------------------------------------------ #
    # Renderers
    # ------------------------------------------------------------------ #
    def _render(self, template_name, context, output_path: Path):
        depth = len(output_path.relative_to(self.output_dir).parts) - 1
        site_root = "../" * depth if depth > 0 else ""
        context.setdefault("site_root", site_root)
        tmpl = self.jinja.get_template(template_name)
        html = tmpl.render(**context)
        self._ensure_dir(output_path.parent)
        output_path.write_text(html, encoding="utf-8")
        print(f"  [GEN] {output_path.relative_to(self.output_dir)}")

    @staticmethod
    def _fix_relative_paths(html: str, site_root: str) -> str:
        def repl(match):
            attr = match.group(1)
            path = match.group(2)
            if path.startswith(("//", "#", "/")) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", path):
                return match.group(0)
            if path.startswith(site_root):
                return match.group(0)
            return f'{attr}="{site_root}{path}"'
        return re.sub(r'(src|href)="([^"]+)"', repl, html)

    def _build_post(self, post):
        out = self.output_dir / post["url"]
        depth = len(out.relative_to(self.output_dir).parts) - 1
        site_root = "../" * depth if depth > 0 else ""
        post_fixed = dict(post)
        post_fixed["body"] = self._fix_relative_paths(post["body"], site_root)
        current_index = self.posts.index(post)
        ctx = {
            "config": self.config,
            "post": post_fixed,
            "all_posts": self.posts,
            "current_index": current_index,
            "all_tags": dict(self.tags),
            "all_categories": dict(self.categories),
        }
        self._render("post.html", ctx, out)

    def _build_page(self, page):
        out = self.output_dir / page["url"]
        depth = len(out.relative_to(self.output_dir).parts) - 1
        site_root = "../" * depth if depth > 0 else ""
        page = dict(page)
        page["body"] = self._fix_relative_paths(page["body"], site_root)
        ctx = {
            "config": self.config,
            "page": page,
            "all_posts": self.posts,
            "all_tags": dict(self.tags),
            "all_categories": dict(self.categories),
        }
        self._render("page.html", ctx, out)

    def _build_index(self):
        archive_years = {}
        for post in self.posts:
            if post.get("date"):
                y = post["date"].year
                archive_years[y] = archive_years.get(y, 0) + 1
        ctx = {
            "config": self.config,
            "posts": self.posts[:self.config.get("posts_per_page", 10)],
            "all_posts": self.posts,
            "all_tags": dict(self.tags),
            "all_categories": dict(self.categories),
            "archive_years": dict(sorted(archive_years.items(), reverse=True)),
        }
        self._render("index.html", ctx, self.output_dir / "index.html")

    def _build_archive(self):
        ctx = {
            "config": self.config,
            "archives": dict(sorted(self.archives.items(), reverse=True)),
            "all_posts": self.posts,
            "all_tags": dict(self.tags),
            "all_categories": dict(self.categories),
        }
        self._render("archive.html", ctx, self.output_dir / "archive.html")

    def _build_tag_pages(self):
        for tag, posts in self.tags.items():
            slug = self._slugify(tag)
            ctx = {
                "config": self.config,
                "tag": tag,
                "posts": posts,
                "all_posts": self.posts,
                "all_tags": dict(self.tags),
                "all_categories": dict(self.categories),
            }
            out = self.output_dir / "tags" / f"{slug}.html"
            self._render("tag.html", ctx, out)

        # Build tags index (all tags)
        tag_ctx = {
            "config": self.config,
            "all_posts": self.posts,
            "all_tags": dict(self.tags),
            "all_categories": dict(self.categories),
        }
        self._render("tags.html", tag_ctx, self.output_dir / "tags" / "all.html")

    def _build_category_pages(self):
        for cat, posts in self.categories.items():
            slug = self._slugify(cat)
            ctx = {
                "config": self.config,
                "category": cat,
                "posts": posts,
                "all_posts": self.posts,
                "all_tags": dict(self.tags),
                "all_categories": dict(self.categories),
            }
            out = self.output_dir / "categories" / f"{slug}.html"
            self._render("category.html", ctx, out)

    def _build_rss(self):
        tmpl = self.jinja.get_template("rss.xml")
        ctx = {
            "config": self.config,
            "posts": self.posts[:20],
            "build_date": datetime.now(timezone.utc),
        }
        out = self.output_dir / "feed.xml"
        self._render("rss.xml", ctx, out)

    def _prepare_search_data(self):
        """Build search index data and store as JSON string (called before rendering)."""
        import re
        index = []
        for post in self.posts:
            body_text = re.sub(r'<[^>]+>', ' ', post.get("body", ""))
            body_text = re.sub(r'\s+', ' ', body_text).strip()
            index.append({
                "title": post.get("title", ""),
                "url": post.get("url", ""),
                "slug": post.get("slug", ""),
                "authors": [a.get("name", "") for a in post.get("authors", [])],
                "abstract": post.get("abstract", ""),
                "category": post.get("category", ""),
                "tags": post.get("tags", []),
                "date": post.get("date").strftime("%Y-%m-%d") if post.get("date") else "",
                "content": body_text[:3000],
            })
        self._search_json = __import__("json").dumps(index, ensure_ascii=False)

    def _build_search_index(self):
        out = self.output_dir / "search.json"
        out.write_text(self._search_json, encoding="utf-8")
        print(f"  [GEN] {out.relative_to(self.output_dir)}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def build(self):
        print("=" * 60)
        print(" LaTeX-Style Academic Blog Generator ")
        print("=" * 60)

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self._ensure_dir(self.output_dir)

        print("\n[1/5] Loading content...")
        self._load_posts()
        self._load_pages()
        self._prepare_search_data()
        print(f"      Posts: {len(self.posts)}, Pages: {len(self.pages)}")

        print("\n[2/5] Copying static assets...")
        self._copy_static()

        print("\n[3/5] Rendering posts, pages & Zhihu markdown...")
        for p in self.posts:
            self._build_post(p)
            self._build_zhihu_markdown(p)
        for p in self.pages:
            self._build_page(p)

        print("\n[4/5] Rendering index, tags, categories, archives...")
        self._build_index()
        self._build_archive()
        self._build_tag_pages()
        self._build_category_pages()

        print("\n[5/5] Rendering RSS feed & search index...")
        self._build_rss()
        self._build_search_index()

        self._save_cache()

        print("\n" + "=" * 60)
        print(f" Done! Output in: {self.output_dir.relative_to(self.root)}")
        print("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LaTeX-style academic blog generator")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF compilation (for dev preview)")
    args = parser.parse_args()
    builder = BlogBuilder(skip_pdf=args.no_pdf)
    builder.build()


if __name__ == "__main__":
    main()
