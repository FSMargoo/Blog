#!/usr/bin/env python3
"""
LaTeX-style Academic Blog Generator
Compile Markdown to beautiful, LaTeX-level HTML.
"""

import hashlib
import json
import os
import subprocess
import sys
import re
import shutil
import uuid
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import yaml
import frontmatter
from jinja2 import Environment, FileSystemLoader, select_autoescape
import markdown
from pymdownx import superfences, arithmatex


class BlogBuilder:
    def __init__(self, config_path="config.yaml"):
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
        """MD5 of the raw markdown file content."""
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _should_rebuild_pdf(self, post: dict) -> bool:
        """Check whether the PDF needs to be rebuilt (source changed)."""
        key = str(post["path"].relative_to(self.root))
        new_hash = self._content_hash(post["path"])
        old_hash = self._cache.get(key)
        if old_hash != new_hash:
            self._cache[key] = new_hash
            return True
        return False

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

            if line.strip() == "---" or line.strip() == "***":
                out.append("\\vspace{4pt}")
                out.append("\\rule{\\textwidth}{0.5pt}")
                out.append("\\vspace{4pt}")
                i += 1
                continue

            # Headings
            hm = re.match(r"^(#{1,6})\s+(.+)$", line)
            if hm:
                level = len(hm.group(1))
                title = hm.group(2).strip()
                title = self._latex_escape(title)
                if level == 1:
                    out.append(f"\\section{{{title}}}")
                elif level == 2:
                    out.append(f"\\subsection{{{title}}}")
                elif level == 3:
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
        # Protect math first
        math_spans = []
        def save_math(m):
            math_spans.append(m.group(0))
            return f"<MATH{len(math_spans)-1}>"
        text = re.sub(r"\$[^$]+\$", save_math, text)
        text = re.sub(r"\\\(.+?\\\)", save_math, text)

        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
        # Italic
        text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)
        # Inline code
        text = re.sub(r"`([^`]+)`", r"\\texttt{\1}", text)
        # Images ![alt](path) — MUST be before links
        def replace_img(m):
            alt = m.group(1)
            path = m.group(2)
            # Strip fig:key| or tbl:key| prefix from caption
            caption = re.sub(r'^(?:fig|tbl):[a-zA-Z0-9_-]+\|', '', alt)
            return f"\\begin{{figure}}[H]\n\\centering\n\\includegraphics[width=0.85\\textwidth]{{{path}}}\n\\caption{{{caption}}}\n\\end{{figure}}"
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_img, text)
        # Links [text](url)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\\href{\2}{\1}", text)
        # Cross-references
        text = re.sub(r"\[@eq:([^\]]+)\]", r"\\textsf{公式 \\ref{eq:\1}}", text)
        text = re.sub(r"\[@fig:([^\]]+)\]", r"\\textsf{图 \\ref{fig:\1}}", text)
        text = re.sub(r"\[@tbl:([^\]]+)\]", r"\\textsf{表 \\ref{tbl:\1}}", text)

        # Restore math
        for i, m in enumerate(math_spans):
            text = text.replace(f"<MATH{i}>", m)

        return text

    @staticmethod
    def _latex_escape(text: str) -> str:
        """Escape LaTeX special characters in plain text."""
        for ch in ["&", "%", "$", "#", "_", "{", "}", "~", "^"]:
            text = text.replace(ch, "\\" + ch)
        return text

    def _compile_pdf(self, tex_path: Path, out_dir: Path) -> bool:
        """Run xelatex twice to compile a PDF. Returns True on success."""
        out_dir.mkdir(parents=True, exist_ok=True)
        jobname = tex_path.stem
        pdf_path = out_dir / f"{jobname}.pdf"
        for run in (1, 2):
            subprocess.run(
                [
                    "xelatex",
                    "-interaction=nonstopmode",
                    "-output-directory", str(out_dir),
                    "-jobname", jobname,
                    str(tex_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(self.root),   # run from project root for correct relative paths
                timeout=60,
            )
        # Check if PDF was generated (xelatex may return non-zero on warnings)
        ok = pdf_path.exists() and pdf_path.stat().st_size > 0
        if not ok:
            log_path = out_dir / f"{jobname}.log"
            tail = ""
            if log_path.exists():
                lines = log_path.read_text(errors="replace").splitlines()
                tail = "\n".join(lines[-20:])
            print(f"\n  [PDF] xelatex failed:\n{tail}")
        # Clean up aux/log files
        for ext in (".aux", ".log", ".out", ".toc"):
            p = out_dir / f"{jobname}{ext}"
            if p.exists():
                p.unlink()
        return ok

    def _copy_pdf_to_output(self, post: dict) -> None:
        """Copy cached PDF from .tex_build to output directory."""
        post_id = post["id"]
        pdf_src = self.root / ".tex_build" / f"{post_id}.pdf"
        pdf_dst = self.output_dir / post["url"].replace(".html", ".pdf")
        if pdf_src.exists():
            pdf_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf_src, pdf_dst)

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

% ---- Geometry (compact) ----
\\usepackage[paperwidth=190mm,paperheight=260mm,
            top=0.55in,bottom=0.55in,
            left=0.75in,right=0.75in,
            includehead,includefoot]{{geometry}}

% ---- Spacing (tight) ----
\\linespread{{1.0}}
\\setlength{{\\parskip}}{{0.2em plus 0.05em minus 0.05em}}
\\setlength{{\\parindent}}{{1.2em}}
\\setlength{{\\abovedisplayskip}}{{3pt plus 1pt minus 2pt}}
\\setlength{{\\belowdisplayskip}}{{3pt plus 1pt minus 2pt}}
\\setlength{{\\abovedisplayshortskip}}{{0pt plus 1pt}}
\\setlength{{\\belowdisplayshortskip}}{{1pt plus 1pt minus 1pt}}
\\usepackage{{enumitem}}
\\setlist{{nosep,leftmargin=*}}

% ---- Colors ----
\\usepackage{{xcolor}}
\\definecolor{{accent}}{{HTML}}{{8B0000}}
\\definecolor{{dark}}{{HTML}}{{1A1A1A}}
\\definecolor{{muted}}{{HTML}}{{555555}}

% ---- Hyperlinks ----
\\usepackage{{hyperref}}
\\hypersetup{{colorlinks=true,linkcolor=accent,urlcolor=accent,citecolor=accent}}

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
\\usepackage{{fancyvrb}}
\\fvset{{fontsize=\\small,frame=single,framerule=0.4pt,framesep=6pt}}
\\DefineVerbatimEnvironment{{codeverb}}{{Verbatim}}{{}}

% ---- Graphics ----
\\usepackage{{graphicx}}
\\usepackage{{float}}
\\graphicspath{{ {{content/}} }}

% ---- Math ----
\\usepackage{{amsmath}}

% ---- Captions ----
\\usepackage{{caption}}
\\captionsetup{{font={{small,sf}},labelfont={{bf,color=accent}},labelsep=period,skip=4pt}}

% ---- No titling package needed (manual compact header) ----

% ---- Section headings (compact) ----
\\usepackage{{titlesec}}
\\titleformat{{\\section}}{{\\large\\bfseries\\color{{dark}}}}{{\\thesection}}{{0.6em}}{{}}[\\vspace{{-2pt}}\\rule{{\\textwidth}}{{0.5pt}}]
\\titleformat{{\\subsection}}{{\\normalsize\\bfseries\\color{{dark}}}}{{\\thesubsection}}{{0.6em}}{{}}
\\titleformat{{\\subsubsection}}{{\\normalsize\\bfseries\\color{{dark}}}}{{\\thesubsubsection}}{{0.6em}}{{}}
\\titlespacing{{\\section}}{{0pt}}{{10pt plus 2pt}}{{4pt plus 2pt}}
\\titlespacing{{\\subsection}}{{0pt}}{{8pt plus 2pt}}{{3pt plus 2pt}}
\\titlespacing{{\\subsubsection}}{{0pt}}{{6pt plus 2pt}}{{2pt plus 2pt}}

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

        # Get raw markdown content (strip frontmatter), preprocess equations
        import frontmatter as fm
        raw = fm.load(str(post["path"]))
        raw_content, _ = self._preprocess_equations(raw.content)
        body = self._markdown_to_latex(raw_content)

        # Build LaTeX preamble (static, with config baked in)
        preamble = self._build_preamble()

        # Render LaTeX template
        tex_tmpl = self.jinja.get_template("article.tex")
        tex_content = tex_tmpl.render(
            preamble=preamble,
            journal_name=self.config.get("journal", {}).get("name", "Blog"),
            author_name=self.config.get("author", ""),
            title=post.get("title", ""),
            authors=authors,
            affiliations=affiliations,
            date=post.get("date").strftime("%Y-%m-%d") if post.get("date") else "",
            abstract=abstract,
            keywords=keywords,
            category=post.get("category", ""),
            doi=post.get("doi", ""),
            body=body,
        )

        tex_path.write_text(tex_content, encoding="utf-8")

        # Compile
        print(f"  [PDF] Compiling {post['id']} ... ", end="", flush=True)
        ok = self._compile_pdf(tex_path, tex_dir)
        if ok:
            pdf_src = tex_dir / f"{post_id}.pdf"
            pdf_dst = self.output_dir / post["url"].replace(".html", ".pdf")
            pdf_dst.parent.mkdir(parents=True, exist_ok=True)
            if pdf_src.exists():
                shutil.copy2(pdf_src, pdf_dst)
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
    def _preprocess_equations(content):
        """Pre-process equation blocks before markdown conversion.

        - Wraps \\begin{equation} / \\begin{align} in \\[ ... \\] for arithmatex.
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
            env = match.group(1)
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
                f'\\begin{{{env}}}\\tag{{{eq_counter}}}\n'
                f'{body.strip()}\n'
                f'\\end{{{env}}}\n'
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
            src_m = re.search(r'src="([^"]*)"', rest)
            src = src_m.group(1) if src_m else ""
            return (
                f'<figure id="fig:{key}" class="numbered-fig">\n'
                f'  <img src="{src}" alt="{caption}">\n'
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

    def _parse_markdown(self, path: Path):
        post = frontmatter.load(str(path))

        raw_bib = post.metadata.get("bibliography", [])
        bib_entries = self._normalize_bibliography(raw_bib)
        bib_map = {key: i for i, (key, _) in enumerate(bib_entries, start=1)}

        # Preprocess: [@key] → [^N]
        content = self._preprocess_citations(post.content, bib_map)

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
            **post.metadata,
            "title": post.metadata.get("title", "Untitled"),
            "date": post.metadata.get("date"),
            "updated": post.metadata.get("updated"),
            "authors": post.metadata.get("authors", []),
            "abstract": post.metadata.get("abstract", ""),
            "keywords": post.metadata.get("keywords", []),
            "tags": post.metadata.get("tags", []),
            "category": post.metadata.get("category", "Uncategorized"),
            "doi": post.metadata.get("doi", ""),
            "bibliography": post.metadata.get("bibliography", []),
            "banner": post.metadata.get("banner", ""),
            "draft": post.metadata.get("draft", False),
            "id": self._article_id(path),
            "slug": post.metadata.get("slug", self._slugify(post.metadata.get("title", "untitled"))),
            "path": path,
            "body": body,
            "toc": toc,
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
            # Build PDF if source changed
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
        context.setdefault("search_json", self._search_json)
        tmpl = self.jinja.get_template(template_name)
        html = tmpl.render(**context)
        self._ensure_dir(output_path.parent)
        output_path.write_text(html, encoding="utf-8")
        print(f"  [GEN] {output_path.relative_to(self.output_dir)}")

    @staticmethod
    def _fix_relative_paths(html: str, site_root: str) -> str:
        import re
        def repl(match):
            attr = match.group(1)
            path = match.group(2)
            if path.startswith(("http://", "https://", "//", "#", "data:")):
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
            "build_date": datetime.utcnow(),
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

        print("\n[3/5] Rendering posts & pages...")
        for p in self.posts:
            self._build_post(p)
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
    builder = BlogBuilder()
    builder.build()


if __name__ == "__main__":
    main()
