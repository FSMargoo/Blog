#!/usr/bin/env python3
"""
LaTeX-style Academic Blog Generator
Compile Markdown to beautiful, LaTeX-level HTML.
"""

import os
import sys
import re
import shutil
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
    def _process_numbered_refs(body):
        """Post-process HTML: auto-number figures/tables and resolve [@fig:key] / [@tbl:key] refs.

        Figure syntax in markdown:  ![fig:alias|Caption text](path/to/img.png)
        Table syntax in markdown:    [@tbl:alias|Caption text]  (line immediately before the table)
        Reference in text:           [@fig:alias]  or  [@tbl:alias]
        """
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

        # Pass 3: Resolve [@fig:key] and [@tbl:key] to numbered links
        def replace_ref(match):
            prefix = match.group(1)
            key = match.group(2)
            if prefix == "fig" and key in fig_aliases:
                return f'<a href="#fig:{key}" class="xref">图 {fig_aliases[key]}</a>'
            if prefix == "tbl" and key in tbl_aliases:
                return f'<a href="#tbl:{key}" class="xref">表 {tbl_aliases[key]}</a>'
            return match.group(0)

        body = re.sub(r'\[@(fig|tbl):([a-zA-Z0-9_-]+)\]', replace_ref, body)

        return body

    def _parse_markdown(self, path: Path):
        post = frontmatter.load(str(path))

        raw_bib = post.metadata.get("bibliography", [])
        bib_entries = self._normalize_bibliography(raw_bib)
        bib_map = {key: i for i, (key, _) in enumerate(bib_entries, start=1)}

        # Preprocess: [@key] → [^N]
        content = self._preprocess_citations(post.content, bib_map)

        # Inject bibliography as footnote definitions
        if bib_entries:
            content += "\n\n"
            for key, text in bib_entries:
                content += f"[^{bib_map[key]}]: {text}\n"

        body = self.md.convert(content)
        body = self._process_numbered_refs(body)
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
            meta["url"] = f"posts/{meta['slug']}.html"
            self.posts.append(meta)

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
            meta["url"] = f"pages/{meta['slug']}.html"
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

        print("\n" + "=" * 60)
        print(f" Done! Output in: {self.output_dir.relative_to(self.root)}")
        print("=" * 60)


def main():
    builder = BlogBuilder()
    builder.build()


if __name__ == "__main__":
    main()
