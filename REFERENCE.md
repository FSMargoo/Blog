# M. Argoo Research Blog -- Reference Manual

A static site generator that produces a journal-style academic blog. Markdown
content with YAML frontmatter is compiled into HTML pages styled after ACM,
Nature, and Science typography.

## Project Structure

```
.
├── build.py              # Build script
├── create_article.py     # Interactive article creation wizard (TUI)
├── serve.py              # Local preview server with live-reload
├── deploy.py             # Deploy to GitHub Pages
├── config.yaml           # Site configuration
├── requirements.txt      # Python dependencies
├── content/              # Source content (markdown)
│   ├── posts/            #   Blog posts (.md)
│   ├── pages/            #   Static pages (.md)
│   └── assets/           #   Images and other assets
├── templates/            # Jinja2 HTML templates
├── static/               # Static files (CSS, JS, fonts)
│   └── css/
│       └── style.css
└── public/               # Build output (gitignored)
```

## Quick Start

```
pip install -r requirements.txt

# Create a new article (interactive wizard)
python create_article.py

# Build the site
python build.py

# Preview locally (build + serve, auto-rebuild on changes)
python serve.py -w
```

Output is written to `public/`. The `serve.py` command starts a local HTTP server
so you can preview the full site at `http://localhost:8000`.

## Configuration

`config.yaml` controls site-wide settings:

| Key | Description |
|-----|-------------|
| `site_name` | Site title used in `<title>` and RSS |
| `site_subtitle` | Subtitle shown in masthead |
| `author` | Default author name |
| `description` | Meta description tag |
| `base_url` | Base URL for deployment (e.g. `https://example.com`) |
| `language` | HTML lang attribute (e.g. `zh-CN`) |
| `journal.name` | Journal name displayed in masthead |
| `journal.issn` | ISSN displayed in footer |
| `journal.volume_prefix` | Prefix before volume number |
| `journal.issue_prefix` | Prefix before issue number |
| `output_dir` | Build output directory (default: `public`) |
| `content_dir` | Content source directory (default: `content`) |
| `template_dir` | Template directory (default: `templates`) |
| `static_dir` | Static assets directory (default: `static`) |
| `posts_per_page` | Number of posts on homepage |
| `date_format` | Date format string |
| `katex.enabled` | Enable KaTeX math rendering |
| `katex.css` | KaTeX CSS CDN URL |
| `katex.js` | KaTeX JS CDN URL |
| `katex.auto_render` | KaTeX auto-render CDN URL |
| `latex_macros` | Build-time custom math macro definitions |

## Frontmatter Reference

Each post (`.md` file in `content/posts/`) begins with YAML frontmatter
delimited by `---`. All fields except `title` are optional.

```yaml
---
title: "Paper Title"
date: "2024-08-20"
updated: "2024-09-01"
banner: "assets/images/banner.png"
authors:
  - name: "Author Name"
    affiliation: "University, Department"
    email: "author@example.edu"
abstract: |
  Abstract text. Multiple lines are joined with spaces.
keywords: ["keyword one", "keyword two"]
tags: ["Tag A", "Tag B"]
category: "Computer Science"
doi: "10.1234/example.2024"
draft: false
slug: "custom-url-slug"
bibliography:
  key1: "Reference text."
  key2: "Reference text."
latex_macros:
  esm:
    args: 1
    body: '\left\langle #1\right\rangle'
---
```

### Field Details

**title** (required)
: Post title. Also used to generate the URL slug unless overridden.

**date**
: Publication date in `YYYY-MM-DD` format. Posts are sorted by this field.

**updated**
: Revision date in `YYYY-MM-DD` format. Shown next to the received date.

**banner**
: Path to a banner image relative to the content directory. Displayed on the
  homepage featured section and category/tag listing pages.

**authors**
: List of author objects. Each author may have `name`, `affiliation`, and
  `email`. Author names appear with superscript affiliation markers on the
  article page.

**abstract**
: Abstract text. Use `|` for multi-line abstracts. Displayed on the article
  page, homepage, and in search results.

**keywords**
: List of keyword strings. Displayed below the abstract.

**tags**
: List of topic tags. Each tag gets its own page listing all posts with that
  tag. Tags are displayed as links on the post page and in article listings.

**category**
: Single category string. Each category gets its own listing page. Displayed
  in the article header and sidebar.

**doi**
: Digital Object Identifier. Displayed in article metadata.

**draft**
: If `true`, the post is skipped during build.

**slug**
: Custom URL slug. Defaults to a slugified version of the title.

**bibliography**
: Reference list. Supports two formats (see Citations below).

**latex_macros**
: Per-post custom math macro definitions. These are expanded at build time and
  must not duplicate a macro already defined in `config.yaml`.

## Citations

References are defined in the `bibliography` frontmatter field and cited in
the body with `[@key]` syntax. The build system automatically numbers
references, generates clickable footnote links, and renders a reference list
with backlinks at the end of the article.

### Bibliography Formats

**Recommended: key-value dict**

```yaml
bibliography:
  lamport1998: "Lamport, L. The Part-Time Parliament. ACM TOCS, 1998."
  ongaro2014: "Ongaro, D. & Ousterhout, J. In Search of an Understandable Consensus Algorithm. USENIX ATC, 2014."
```

Keys are arbitrary alphanumeric identifiers. Use a convention like
`authorYear` for readability. Order in the YAML dict determines reference
numbers (Python 3.7+ preserves insertion order).

**Legacy: list of strings**

```yaml
bibliography:
  - "Lamport, L. The Part-Time Parliament. ACM TOCS, 1998."
  - "Ongaro, D. & Ousterhout, J. In Search of an Understandable Consensus Algorithm. USENIX ATC, 2014."
```

Auto-generated keys are `ref1`, `ref2`, etc.

### Citing in Text

```
Fischer, Lynch, and Paterson proved a landmark theorem [@fischer1985].

Multiple citations: [@lamport1998; @ongaro2014]
```

Renders as clickable superscript numbers linking to the reference list. Each
reference entry includes a backlink to return to the citation point.

## Figures and Tables

Figures and tables receive automatic numbering and can be referenced by alias
in the text.

### Numbered Figures

Use the prefix `fig:alias|` in the image alt text:

```markdown
![fig:arch|System architecture overview](assets/images/arch.png)
```

Renders as:

```
Figure 1: System architecture overview
```

The alias `arch` creates an anchor `#fig:arch` that can be referenced.

You can optionally add a width directive at the end of the alt text:

```markdown
![fig:arch|System architecture overview|width=60%](assets/images/arch.png)
![fig:arch|System architecture overview|width=9cm](assets/images/arch.png)
```

Supported width values are percentages and standard LaTeX length units such as
`pt`, `mm`, `cm`, `in`, `em`, and `ex`. HTML uses the requested width directly;
PDF output caps image width at the text column width so large images do not
overflow the page.

### Numbered Tables

Place a marker on the line immediately before a markdown table:

```markdown
[@tbl:throughput|Throughput comparison across failure models (ops/s)]

| Model | 5 nodes | 10 nodes | 20 nodes |
|-------|---------|----------|----------|
| None  | 48,200  | 31,500   | 18,400   |
| Crash | 45,100  | 28,900   | 15,700   |
| BFT   | 22,300  | 11,200   | 4,800    |
```

Renders as:

```
Table 1: Throughput comparison across failure models (ops/s)
```

The alias `throughput` creates an anchor `#tbl:throughput`.

### Regular Images

Images without the `fig:` prefix are rendered as plain `<img>` elements with
no numbering or caption wrapper:

```markdown
![A descriptive alt text](assets/images/photo.png)
```

## Math

KaTeX is enabled by default. Use standard LaTeX math syntax:

```markdown
Inline: $E = mc^2$

Display:
$$
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
$$
```

Delimiters `\(...\)` and `\[...\]` are also supported.

### Custom LaTeX Math Macros

Custom math macros are expanded at build time before HTML, PDF, search index,
RSS, and Zhihu Markdown are generated. This is a source-level expansion system,
not runtime KaTeX `macros`, so every output format sees the same final LaTeX.

Define global macros in `config.yaml`:

```yaml
latex_macros:
  esm:
    args: 1
    body: '\left\langle #1\right\rangle'
  R:
    args: 0
    body: '\mathbb{R}'
```

Or define post-local macros in a post's frontmatter:

```yaml
---
title: "Example"
latex_macros:
  esm:
    args: 1
    body: '\left\langle #1\right\rangle'
  norm:
    args: 1
    body: '\left\lVert #1\right\rVert'
  R:
    args: 0
    body: '\mathbb{R}'
---
```

Zero-argument macros may also use the short form:

```yaml
latex_macros:
  R: '\mathbb{R}'
```

Call macros with normal LaTeX command syntax inside math:

```markdown
Inline: $\esm{x}\in\R$
Nested: $\norm{\esm{\frac{a}{b}}}$
Display:
$$
\esm{\frac{a}{b}} = \left\langle \frac{a}{b}\right\rangle
$$
```

After expansion, the examples above become ordinary LaTeX such as
`\left\langle x\right\rangle` and `\mathbb{R}`.

#### Macro Definition Syntax

Each full-form macro definition has these fields:

| Field | Required | Description |
|-------|----------|-------------|
| `args` | Yes | Number of braced arguments, from `0` to `9` |
| `body` | Yes | Replacement LaTeX body, using `#1`, `#2`, ... for arguments |

Example with two arguments:

```yaml
latex_macros:
  pair:
    args: 2
    body: '\left(#1,#2\right)'
```

Usage:

```markdown
$\pair{x}{\frac{a}{b}}$
```

Expansion:

```latex
$\left(x,\frac{a}{b}\right)$
```

#### Expansion Scope

Expansion only runs inside math regions:

- Inline math: `$...$` and `\(...\)`
- Display math: `$$...$$` and `\[...\]`
- Supported LaTeX math environments, including `equation`, `align`,
  `aligned`, `gather`, `multline`, `split`, `cases`, and matrix environments

Fenced code blocks, inline code spans, links, image paths, and ordinary prose
are left unchanged. For example:

```markdown
Prose \esm{x} stays literal.
Code `$\esm{x}$` stays literal.
Math $\esm{x}$ expands.
```

#### Validation Rules

- Macro names must contain letters only, without the leading backslash in the
  YAML key.
- Arguments are written as `#1`, `#2`, ... in the macro body and must be
  passed with braces: `\esm{x}`.
- Expansion is brace-aware, so `\esm{\frac{a}{b}}` is parsed as one argument.
- Post-local macros may not redefine a global macro from `config.yaml`.
- Built-in or reserved LaTeX commands such as `\frac`, `\sqrt`, `\left`,
  `\right`, `\mathbb`, `\begin`, and `\end` cannot be redefined.
- Missing arguments, unbalanced braces, invalid parameter markers such as `#0`
  or `#3` in a one-argument macro, and recursive macro definitions stop the
  build with a `LatexMacroError`.

#### Failure Example

This definition fails because `body` references `#2`, but `args` is `1`:

```yaml
latex_macros:
  bad:
    args: 1
    body: '#2'
```

This pair also fails because the definitions are recursive:

```yaml
latex_macros:
  a:
    args: 0
    body: '\b'
  b:
    args: 0
    body: '\a'
```

### Numbered Equations

Use `\begin{equation}` and add an optional `\label{eq:alias}` for
cross-referencing:

```markdown
\begin{equation}
\label{eq:rendering}
L_o(\mathbf{x}, \boldsymbol{\omega}_o) = \int_{\Omega}
f_r(\mathbf{x}, \boldsymbol{\omega_i}, \boldsymbol{\omega_o})
L_i(\mathbf{x}, \boldsymbol{\omega_i})
(\boldsymbol{\omega_i} \cdot \mathbf{n}) \, d\boldsymbol{\omega_i}
\end{equation}
```

Renders as a numbered display equation:

```
                  L_o(x, ω_o) = ∫_Ω f_r(x, ω_i, ω_o) L_i(x, ω_i) (ω_i · n) dω_i   (1)
```

The alias `rendering` creates an anchor `#eq:rendering` that can be
referenced (see Cross-References below).  Equations without `\label` are
still auto-numbered sequentially.

The `\begin{align}` environment is also supported for multi-line numbered
equations.

### Cross-References

Reference figures, tables, and equations in the text:

```markdown
The system architecture is shown in [@fig:arch].
Throughput results are summarized in [@tbl:throughput].
As derived from the rendering equation [@eq:rendering], ...
```

Renders as clickable links: "图 1", "表 1", and "公式 1".  The prefixes
`fig:`, `tbl:`, and `eq:` determine the link target; the alias after the
colon must match a `\label` (for equations) or the alt-text key (for
figures and tables).

## Code Blocks

Fenced code blocks with a language tag get syntax highlighting via Pygments:

````markdown
```python
def consensus(node, value):
    ...
```
````

## Draft Posts

Set `draft: true` in the frontmatter to exclude a post from the build:

```yaml
---
title: "Work in Progress"
draft: true
---
```

## Search

A client-side search index is generated at `public/search.json`. The search
modal is opened with `Ctrl+K` or by clicking "Search" in the navigation bar.
Search matches against titles, abstracts, author names, tags, categories, and
body text.

## RSS

An RSS feed is generated at `public/feed.xml`. The feed includes the 20 most
recent posts. A link to the feed appears in the sidebar and navigation.

## Templates

Jinja2 templates in `templates/` control the HTML output:

| Template | Purpose |
|----------|---------|
| `base.html` | Masthead, navigation, search, footer (shared by all pages) |
| `index.html` | Homepage with featured article and recent papers list |
| `post.html` | Individual article page |
| `archive.html` | Chronological list of all papers grouped by month |
| `category.html` | Papers grouped by category |
| `tag.html` | Papers grouped by tag |
| `tags.html` | Index of all tags |
| `page.html` | Static page (from `content/pages/`) |
| `rss.xml` | RSS feed template |

Template variables available in all contexts:

| Variable | Description |
|----------|-------------|
| `config` | Full site configuration dict |
| `site_root` | Relative path to site root (`../..` etc.) |
| `all_posts` | List of all published posts (sorted by date) |
| `all_tags` | Dict mapping tag name to list of posts |
| `all_categories` | Dict mapping category name to list of posts |

Additional variables are available in specific templates (e.g. `post` in
`post.html`, `posts` in `tag.html`).

## Article Creation Wizard

`create_article.py` is an interactive TUI (Terminal User Interface) wizard that
guides you through creating a new article step by step. It ensures all
frontmatter fields are correctly filled in before writing the `.md` file.

```
python create_article.py
```

### Wizard Steps

The wizard walks through 7 screens:

| Step | Screen | What you set |
|------|--------|-------------|
| 1 | Title & Category | Title (required), URL slug (auto-generated), category |
| 2 | Metadata | Date (defaults to today), updated date, banner image, DOI, draft toggle |
| 3 | Authors | Add/remove authors with name, affiliation, and email |
| 4 | Abstract | Multi-line Markdown abstract |
| 5 | Keywords & Tags | Comma-separated keywords and tags, with live chip preview |
| 6 | Bibliography | Add/remove references (citation key + text) |
| 7 | Review & Save | Full YAML frontmatter preview, then save to `content/posts/` |

### Navigation

| Key | Action |
|-----|--------|
| `Ctrl+N` | Next step |
| `Ctrl+P` | Previous step |
| `Ctrl+Q` | Quit (discard) |
| Click buttons | Navigate with mouse |

### Generated File

The wizard writes to `content/posts/<slug>.md` with a complete YAML frontmatter
and a body template skeleton:

```markdown
---
title: "My Article Title"
date: "2026-06-10"
category: Research
authors:
  - name: "Author Name"
    affiliation: "University"
    email: "author@example.edu"
abstract: |
  Abstract text goes here…
keywords: ["keyword1", "keyword2"]
tags: ["Tag A"]
slug: my-article-title
---

## 1. Introduction

...

## 2. Background

...

...
```

If the slug already exists, the wizard warns you before overwriting.

## Local Preview Server

`serve.py` builds the site and starts a local HTTP server so you can preview
the blog in a browser before deploying.

```
python serve.py                 # build + serve on port 8000
python serve.py --no-build      # skip build, serve existing public/
python serve.py -w              # build + serve + auto-rebuild on changes
python serve.py -p 3000 -w -v   # custom port, watch, verbose logging
```

### Options

| Flag | Purpose |
|------|---------|
| `-p, --port PORT` | Listen on PORT (default: 8000) |
| `-b, --bind ADDR` | Bind address (default: 127.0.0.1) |
| `--no-build` | Skip `build.py`, serve existing `public/` |
| `-w, --watch` | Watch `content/`, `templates/`, `static/`, `config.yaml` for changes and auto-rebuild |
| `-v, --verbose` | Log every HTTP request (default: errors and redirects only) |

### How it works

1. Runs `python build.py` to generate `public/` (unless `--no-build`).
2. Starts a `ThreadingHTTPServer` rooted at `public/`.
3. Prints the local URL — open `http://localhost:8000` in a browser.
4. If `--watch` is set, polls source directories every 1.5 seconds. When a
   file changes, it re-runs the build automatically.
5. Press `Ctrl+C` to stop.

### Typical workflow

```bash
# Start the preview server with auto-rebuild
python serve.py -w

# In another terminal, create or edit articles, then rebuild:
python create_article.py       # create a new post
# ... or edit content/posts/*.md directly — the watcher rebuilds for you

# Refresh the browser to see changes immediately.
```

## Deployment

The `public/` directory is gitignored. A common workflow is to deploy it to a
separate repository (e.g. for GitHub Pages):

```
python build.py
cd public
git init
git add -A
git commit -m "Deploy"
git push https://github.com/user/user.github.io.git main
```
