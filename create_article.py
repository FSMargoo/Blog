#!/usr/bin/env python3
"""
Interactive TUI wizard for creating new journal-style blog articles.

Walk through 7 steps to fill in frontmatter and generate a Markdown
template in content/posts/<slug>.md ready for writing.

Usage:
    python create_article.py
"""

from __future__ import annotations

import re
from pathlib import Path
from datetime import date
from dataclasses import dataclass, field

import yaml
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import (
    Container,
    Horizontal,
    Vertical,
    VerticalScroll,
    Center,
)
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Static,
    Switch,
    TextArea,
)
from textual import on

# ------------------------------------------------------------------ #
# Project paths
# ------------------------------------------------------------------ #
ROOT = Path(__file__).parent.resolve()
CONTENT_DIR = ROOT / "content"
POSTS_DIR = CONTENT_DIR / "posts"

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def slugify(text: str) -> str:
    """Slugify a string, same logic as build.py."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def validate_date(s: str) -> bool:
    """Check YYYY-MM-DD validity."""
    if not s:
        return True
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s))


# ------------------------------------------------------------------ #
# Shared article state
# ------------------------------------------------------------------ #


@dataclass
class ArticleData:
    """Mutable bag of all frontmatter fields collected across screens."""

    title: str = ""
    slug: str = ""
    category: str = "Uncategorized"
    date: str = field(default_factory=today_str)
    updated: str = ""
    banner: str = ""
    doi: str = ""
    draft: bool = False
    authors: list[dict] = field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    bibliography: dict[str, str] = field(default_factory=dict)


# ------------------------------------------------------------------ #
# Modals
# ------------------------------------------------------------------ #


class AuthorModal(ModalScreen[dict | None]):
    """Modal for adding or editing an author."""

    DEFAULT_CSS = """
    AuthorModal {
        align: center middle;
    }
    AuthorModal > Vertical {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    AuthorModal Label {
        margin-top: 1;
    }
    AuthorModal Input {
        width: 100%;
    }
    AuthorModal Horizontal {
        margin-top: 1;
        align-horizontal: right;
    }
    AuthorModal Button {
        margin-left: 1;
    }
    """

    def __init__(self, existing: dict | None = None):
        super().__init__()
        self.existing = existing or {}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold]Add Author[/bold]")
            yield Label("Name:")
            yield Input(
                value=self.existing.get("name", ""),
                id="author-name",
                placeholder="Author name",
            )
            yield Label("Affiliation:")
            yield Input(
                value=self.existing.get("affiliation", ""),
                id="author-affiliation",
                placeholder="University / Institution",
            )
            yield Label("Email:")
            yield Input(
                value=self.existing.get("email", ""),
                id="author-email",
                placeholder="author@example.edu",
            )
            with Horizontal():
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Add ✓", variant="primary", id="add")

    @on(Button.Pressed, "#cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#add")
    def handle_add(self) -> None:
        name = self.query_one("#author-name", Input).value.strip()
        if not name:
            self.notify("Author name is required.", severity="warning")
            return
        result = {"name": name}
        aff = self.query_one("#author-affiliation", Input).value.strip()
        if aff:
            result["affiliation"] = aff
        email = self.query_one("#author-email", Input).value.strip()
        if email:
            result["email"] = email
        self.dismiss(result)


class ReferenceModal(ModalScreen[tuple[str, str] | None]):
    """Modal for adding a bibliography reference (key + text)."""

    DEFAULT_CSS = """
    ReferenceModal {
        align: center middle;
    }
    ReferenceModal > Vertical {
        width: 70;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    ReferenceModal Label {
        margin-top: 1;
    }
    ReferenceModal Input {
        width: 100%;
    }
    ReferenceModal TextArea {
        height: 5;
        margin-top: 1;
    }
    ReferenceModal Horizontal {
        margin-top: 1;
        align-horizontal: right;
    }
    ReferenceModal Button {
        margin-left: 1;
    }
    """

    def __init__(self, existing_key: str = "", existing_text: str = ""):
        super().__init__()
        self.existing_key = existing_key
        self.existing_text = existing_text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold]Add Reference[/bold]")
            yield Label("Citation Key  (e.g.  lamport1998):")
            yield Input(
                value=self.existing_key,
                id="ref-key",
                placeholder="lamport1998",
            )
            yield Label("Reference Text:")
            yield TextArea(self.existing_text, id="ref-text")
            with Horizontal():
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Add ✓", variant="primary", id="add")

    @on(Button.Pressed, "#cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#add")
    def handle_add(self) -> None:
        key = self.query_one("#ref-key", Input).value.strip()
        text = self.query_one("#ref-text", TextArea).text.strip()
        if not key:
            self.notify("Citation key is required.", severity="warning")
            return
        if not text:
            self.notify("Reference text is required.", severity="warning")
            return
        self.dismiss((key, text))


# ------------------------------------------------------------------ #
# Step Screens
# ------------------------------------------------------------------ #

# Shared CSS for all step screens
_STEP_CSS = """
StepScreen {
    align: center middle;
}
StepScreen > VerticalScroll {
    width: 70;
    max-height: 90%;
    background: $surface;
    border: thick $primary;
    padding: 1 2;
}
StepScreen .step-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}
StepScreen Label {
    margin-top: 1;
    color: $text-muted;
}
StepScreen Input {
    width: 100%;
}
StepScreen TextArea {
    height: 10;
    margin-top: 1;
}
StepScreen Switch {
    margin-top: 1;
}
StepScreen .preview {
    margin-top: 1;
    padding: 1;
    background: $surface-darken-1;
    color: $text;
    min-height: 3;
}
StepScreen .list-display {
    margin-top: 1;
    padding: 1;
    background: $surface-darken-1;
    color: $text;
    min-height: 5;
}
StepScreen Horizontal.nav {
    margin-top: 1;
    align-horizontal: right;
}
StepScreen Horizontal.nav Button {
    margin-left: 1;
}
StepScreen .hint {
    color: $text-disabled;
    text-style: italic;
}
StepScreen .slug-row {
    layout: horizontal;
    margin-top: 1;
}
StepScreen .slug-row Label {
    margin-top: 0;
    margin-right: 1;
    width: 12;
}
StepScreen .slug-row Input {
    width: 1fr;
}
"""


class StepScreen(Screen):
    """Base mixin providing back/next navigation and shared layout."""

    DEFAULT_CSS = _STEP_CSS

    BINDINGS = [
        Binding("ctrl+n", "next", "Next step", show=True),
        Binding("ctrl+p", "back", "Previous step", show=True),
    ]

    def __init__(self, data: ArticleData):
        super().__init__()
        self.data = data

    def action_next(self) -> None:
        """Go to next step (override in subclass) — bound to Ctrl+N."""
        self._find_app().go_next()

    def action_back(self) -> None:
        """Go to previous step — bound to Ctrl+P."""
        self._find_app().go_back()

    def _find_app(self):
        """Return the ArticleWizardApp instance."""
        return self.app


# ------------------------------------------------------------------ #
# Step 1 — Title & Category
# ------------------------------------------------------------------ #


class TitleScreen(StepScreen):
    """Step 1: Title, auto-slug, and category."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Step 1/7  —  Basic Information", classes="step-title")

            yield Label("[bold]Title[/bold]  (required)")
            yield Input(
                value=self.data.title,
                id="title",
                placeholder="e.g. A Novel Approach to Consensus Protocols",
            )

            yield Label("[bold]Slug[/bold]  (auto-generated, can override)")
            with Container(classes="slug-row"):
                yield Label("content/posts/")
                yield Input(
                    value=self.data.slug,
                    id="slug",
                    placeholder="auto-generated-from-title",
                )
            yield Static("", id="slug-preview", classes="hint")

            yield Label("[bold]Category[/bold]")
            yield Input(
                value=self.data.category,
                id="category",
                placeholder="e.g. Computer Science, Mathematics",
            )

            with Horizontal(classes="nav"):
                yield Button("←  Back", variant="default", id="back", disabled=True)
                yield Button("Next  →", variant="primary", id="next")

    def on_mount(self) -> None:
        self._update_slug_preview()
        self.query_one("#title", Input).focus()

    @on(Input.Changed, "#title")
    def _on_title_changed(self, event: Input.Changed) -> None:
        """Auto-fill slug from title."""
        if not event.value:
            return
        auto = slugify(event.value)
        slug_input = self.query_one("#slug", Input)
        # Only auto-update if user hasn't manually edited the slug
        current_slug = slug_input.value
        current_title_slug = slugify(self.data.title) if self.data.title else ""
        if not current_slug or current_slug == current_title_slug:
            slug_input.value = auto
        self.data.title = event.value
        self._update_slug_preview()

    @on(Input.Changed, "#slug")
    def _on_slug_changed(self, event: Input.Changed) -> None:
        self.data.slug = event.value
        self._update_slug_preview()

    @on(Input.Changed, "#category")
    def _on_category_changed(self, event: Input.Changed) -> None:
        self.data.category = event.value or "Uncategorized"

    def _update_slug_preview(self) -> None:
        slug = self.query_one("#slug", Input).value or "(empty)"
        self.query_one("#slug-preview", Static).update(
            f"File will be saved to: [italic]content/posts/{slug}.md[/italic]"
        )

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self._find_app().go_back()

    @on(Button.Pressed, "#next")
    def handle_next(self) -> None:
        title = self.query_one("#title", Input).value.strip()
        if not title:
            self.notify("Title is required.", severity="error")
            self.query_one("#title", Input).focus()
            return
        self.data.title = title
        slug = self.query_one("#slug", Input).value.strip()
        self.data.slug = slug or slugify(title)
        self._find_app().go_next()


# ------------------------------------------------------------------ #
# Step 2 — Metadata
# ------------------------------------------------------------------ #


class MetadataScreen(StepScreen):
    """Step 2: Date, updated, banner, DOI, draft toggle."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Step 2/7  —  Metadata & Status", classes="step-title")

            yield Label("[bold]Date[/bold]  (YYYY-MM-DD, defaults to today)")
            yield Input(value=self.data.date, id="date", placeholder="YYYY-MM-DD")

            yield Label("[bold]Updated[/bold]  (revision date, optional)")
            yield Input(value=self.data.updated, id="updated", placeholder="YYYY-MM-DD")

            yield Label("[bold]Banner Image[/bold]  (path relative to content/)")
            yield Input(
                value=self.data.banner,
                id="banner",
                placeholder="assets/images/banner-my-post.png",
            )

            yield Label("[bold]DOI[/bold]  (optional)")
            yield Input(
                value=self.data.doi,
                id="doi",
                placeholder="10.1234/example.2026",
            )

            yield Label("[bold]Draft[/bold]  (draft posts are skipped during build)")
            yield Switch(value=self.data.draft, id="draft")

            with Horizontal(classes="nav"):
                yield Button("←  Back", variant="default", id="back")
                yield Button("Next  →", variant="primary", id="next")

    def on_mount(self) -> None:
        self.query_one("#date", Input).focus()

    @on(Input.Changed, "#date")
    def _on_date(self, event: Input.Changed) -> None:
        self.data.date = event.value

    @on(Input.Changed, "#updated")
    def _on_updated(self, event: Input.Changed) -> None:
        self.data.updated = event.value

    @on(Input.Changed, "#banner")
    def _on_banner(self, event: Input.Changed) -> None:
        self.data.banner = event.value

    @on(Input.Changed, "#doi")
    def _on_doi(self, event: Input.Changed) -> None:
        self.data.doi = event.value

    @on(Switch.Changed, "#draft")
    def _on_draft(self, event: Switch.Changed) -> None:
        self.data.draft = event.value

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self._find_app().go_back()

    @on(Button.Pressed, "#next")
    def handle_next(self) -> None:
        if self.data.date and not validate_date(self.data.date):
            self.notify("Invalid date format. Use YYYY-MM-DD.", severity="error")
            return
        if self.data.updated and not validate_date(self.data.updated):
            self.notify("Invalid updated format. Use YYYY-MM-DD.", severity="error")
            return
        self._find_app().go_next()


# ------------------------------------------------------------------ #
# Step 3 — Authors
# ------------------------------------------------------------------ #


class AuthorsScreen(StepScreen):
    """Step 3: Manage authors list."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Step 3/7  —  Authors", classes="step-title")
            yield Static(self._render_authors(), id="author-list", classes="list-display")
            with Horizontal():
                yield Button("+  Add Author", variant="primary", id="add")
                yield Button("−  Remove Last", variant="default", id="remove")
            with Horizontal(classes="nav"):
                yield Button("←  Back", variant="default", id="back")
                yield Button("Next  →", variant="primary", id="next")

    def _refresh_display(self) -> None:
        try:
            self.query_one("#author-list", Static).update(self._render_authors())
        except Exception:
            pass  # widget not mounted yet

    def _render_authors(self) -> str:
        if not self.data.authors:
            return "[italic]No authors added yet. Click 'Add Author' to add one.[/italic]"
        lines = []
        for i, a in enumerate(self.data.authors, 1):
            parts = [f"[bold]{i}.[/bold] {a.get('name', 'Unnamed')}"]
            if a.get("affiliation"):
                parts.append(f"  ─  [italic]{a['affiliation']}[/italic]")
            if a.get("email"):
                parts.append(f"  ─  {a['email']}")
            lines.append("".join(parts))
        return "\n".join(lines)

    @on(Button.Pressed, "#add")
    def handle_add(self) -> None:
        self.app.push_screen(AuthorModal(), callback=self._on_author_added)

    def _on_author_added(self, result: dict | None) -> None:
        if result is not None:
            self.data.authors.append(result)
            self._refresh_display()

    @on(Button.Pressed, "#remove")
    def handle_remove(self) -> None:
        if self.data.authors:
            removed = self.data.authors.pop()
            self.notify(f"Removed: {removed.get('name', 'Unnamed')}")
            self._refresh_display()

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self._find_app().go_back()

    @on(Button.Pressed, "#next")
    def handle_next(self) -> None:
        self._find_app().go_next()


# ------------------------------------------------------------------ #
# Step 4 — Abstract
# ------------------------------------------------------------------ #


class AbstractScreen(StepScreen):
    """Step 4: Multi-line abstract."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Step 4/7  —  Abstract", classes="step-title")
            yield Label("[bold]Abstract[/bold]  (multi-line, Markdown allowed)")
            yield TextArea(self.data.abstract, id="abstract")
            yield Static(
                f"Characters: {len(self.data.abstract)}", id="char-count", classes="hint"
            )
            with Horizontal(classes="nav"):
                yield Button("←  Back", variant="default", id="back")
                yield Button("Next  →", variant="primary", id="next")

    def on_mount(self) -> None:
        self.query_one("#abstract", TextArea).focus()

    @on(TextArea.Changed, "#abstract")
    def _on_abstract(self, event: TextArea.Changed) -> None:
        self.data.abstract = event.text_area.text
        self.query_one("#char-count", Static).update(
            f"Characters: {len(self.data.abstract)}"
        )

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self._find_app().go_back()

    @on(Button.Pressed, "#next")
    def handle_next(self) -> None:
        self._find_app().go_next()


# ------------------------------------------------------------------ #
# Step 5 — Keywords & Tags
# ------------------------------------------------------------------ #


class KeywordsScreen(StepScreen):
    """Step 5: Keywords and tags."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Step 5/7  —  Keywords & Tags", classes="step-title")

            yield Label("[bold]Keywords[/bold]  (comma-separated)")
            yield Input(
                value=", ".join(self.data.keywords),
                id="keywords",
                placeholder="keyword1, keyword2, keyword3",
            )
            yield Static(self._render_chips(self.data.keywords), id="kw-preview", classes="preview")

            yield Label("[bold]Tags[/bold]  (comma-separated)")
            yield Input(
                value=", ".join(self.data.tags),
                id="tags",
                placeholder="Tag A, Tag B",
            )
            yield Static(self._render_chips(self.data.tags), id="tag-preview", classes="preview")

            with Horizontal(classes="nav"):
                yield Button("←  Back", variant="default", id="back")
                yield Button("Next  →", variant="primary", id="next")

    @staticmethod
    def _render_chips(items: list[str]) -> str:
        if not items:
            return "[italic]None[/italic]"
        return "  ".join(f"[reverse]{kw}[/reverse]" for kw in items)

    def on_mount(self) -> None:
        self.query_one("#keywords", Input).focus()

    @on(Input.Changed, "#keywords")
    def _on_keywords(self, event: Input.Changed) -> None:
        items = [k.strip() for k in event.value.split(",") if k.strip()]
        self.data.keywords = items
        self.query_one("#kw-preview", Static).update(self._render_chips(items))

    @on(Input.Changed, "#tags")
    def _on_tags(self, event: Input.Changed) -> None:
        items = [t.strip() for t in event.value.split(",") if t.strip()]
        self.data.tags = items
        self.query_one("#tag-preview", Static).update(self._render_chips(items))

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self._find_app().go_back()

    @on(Button.Pressed, "#next")
    def handle_next(self) -> None:
        self._find_app().go_next()


# ------------------------------------------------------------------ #
# Step 6 — Bibliography
# ------------------------------------------------------------------ #


class BibliographyScreen(StepScreen):
    """Step 6: Manage bibliography references."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Step 6/7  —  Bibliography", classes="step-title")
            yield Static(
                self._render_refs(), id="bib-list", classes="list-display"
            )
            with Horizontal():
                yield Button("+  Add Reference", variant="primary", id="add")
                yield Button("−  Remove Last", variant="default", id="remove")
            with Horizontal(classes="nav"):
                yield Button("←  Back", variant="default", id="back")
                yield Button("Next  →", variant="primary", id="next")

    def _refresh_display(self) -> None:
        try:
            self.query_one("#bib-list", Static).update(self._render_refs())
        except Exception:
            pass

    def _render_refs(self) -> str:
        if not self.data.bibliography:
            return "[italic]No references yet. Click 'Add Reference' to add one.[/italic]"
        lines = []
        for i, (key, text) in enumerate(self.data.bibliography.items(), 1):
            lines.append(f"[bold]{i}.[/bold]  [{key}]  {text[:120]}{'…' if len(text) > 120 else ''}")
        return "\n\n".join(lines)

    @on(Button.Pressed, "#add")
    def handle_add(self) -> None:
        self.app.push_screen(ReferenceModal(), callback=self._on_ref_added)

    def _on_ref_added(self, result: tuple[str, str] | None) -> None:
        if result is not None:
            key, text = result
            self.data.bibliography[key] = text
            self._refresh_display()

    @on(Button.Pressed, "#remove")
    def handle_remove(self) -> None:
        if self.data.bibliography:
            keys = list(self.data.bibliography.keys())
            last_key = keys[-1]
            del self.data.bibliography[last_key]
            self.notify(f"Removed: [{last_key}]")
            self._refresh_display()

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self._find_app().go_back()

    @on(Button.Pressed, "#next")
    def handle_next(self) -> None:
        self._find_app().go_next()


# ------------------------------------------------------------------ #
# Step 7 — Review & Save
# ------------------------------------------------------------------ #


class ReviewScreen(StepScreen):
    """Step 7: Review generated YAML and save to file."""

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("Step 7/7  —  Review & Save", classes="step-title")
            yield Static(self._build_preview(), id="yaml-preview", classes="preview")
            with Horizontal(classes="nav"):
                yield Button("←  Back", variant="default", id="back")
                yield Button("💾  Save Article", variant="primary", id="save")

    def _build_preview(self) -> str:
        """Generate a rich-text preview of the YAML frontmatter."""
        fm = self._build_frontmatter_dict()
        yaml_str = yaml.dump(
            fm,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).rstrip()
        return f"[bold]---[/bold]\n{yaml_str}\n[bold]---[/bold]\n\n[italic](Markdown body template follows)[/italic]"

    def _build_frontmatter_dict(self) -> dict:
        """Assemble the frontmatter dict, omitting empty/None values."""
        fm: dict = {"title": self.data.title}

        if self.data.date:
            fm["date"] = self.data.date
        if self.data.updated:
            fm["updated"] = self.data.updated
        if self.data.category and self.data.category != "Uncategorized":
            fm["category"] = self.data.category
        if self.data.authors:
            fm["authors"] = [
                {k: v for k, v in a.items() if v} for a in self.data.authors
            ]
        if self.data.abstract.strip():
            fm["abstract"] = self.data.abstract.strip()
        if self.data.keywords:
            fm["keywords"] = self.data.keywords
        if self.data.tags:
            fm["tags"] = self.data.tags
        if self.data.banner:
            fm["banner"] = self.data.banner
        if self.data.doi:
            fm["doi"] = self.data.doi
        if self.data.bibliography:
            fm["bibliography"] = dict(self.data.bibliography)
        if self.data.draft:
            fm["draft"] = True
        if self.data.slug:
            fm["slug"] = self.data.slug

        return fm

    # Use on_mount to refresh the preview each time this screen is shown.
    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            self.query_one("#yaml-preview", Static).update(self._build_preview())
        except Exception:
            pass

    @on(Button.Pressed, "#back")
    def handle_back(self) -> None:
        self._find_app().go_back()

    @on(Button.Pressed, "#save")
    def handle_save(self) -> None:
        fm = self._build_frontmatter_dict()
        slug = self.data.slug or slugify(self.data.title)

        # Ensure content/posts/ directory exists
        POSTS_DIR.mkdir(parents=True, exist_ok=True)

        output_path = POSTS_DIR / f"{slug}.md"
        if output_path.exists():
            self.notify(
                f"File already exists: {output_path.name}\n"
                "Choose a different slug or delete the existing file.",
                severity="error",
            )
            return

        # Serialize frontmatter
        yaml_block = yaml.dump(
            fm,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).rstrip()

        # Body template
        body_template = """## 1. Introduction

...

## 2. Background

...

## 3. ...

...

## References

...
"""

        content = f"---\n{yaml_block}\n---\n\n{body_template}"

        output_path.write_text(content, encoding="utf-8")
        self.notify(
            f"✓  Article created!\n"
            f"   {output_path.relative_to(ROOT)}",
            title="Saved ✓",
            severity="information",
            timeout=10,
        )

        # Exit the app
        self.app.exit()


# ------------------------------------------------------------------ #
# Main App
# ------------------------------------------------------------------ #


class ArticleWizardApp(App):
    """Multi-step TUI wizard for creating journal-style blog articles."""

    TITLE = "📝  Create New Article"
    SUB_TITLE = "M. Argoo Research Blog — Article Wizard"

    BINDINGS = [
        Binding("ctrl+q", "quit_wizard", "Quit", show=True, priority=True),
        Binding("ctrl+n", "next", "Next", show=True),
        Binding("ctrl+p", "back", "Back", show=True),
    ]

    _STEPS = [
        TitleScreen,
        MetadataScreen,
        AuthorsScreen,
        AbstractScreen,
        KeywordsScreen,
        BibliographyScreen,
        ReviewScreen,
    ]

    def __init__(self):
        super().__init__()
        self.data = ArticleData()
        self._step_index = 0

    def on_mount(self) -> None:
        self.push_screen(self._STEPS[0](self.data))

    def go_next(self) -> None:
        """Advance to the next step."""
        if self._step_index < len(self._STEPS) - 1:
            self._step_index += 1
            self.switch_screen(self._STEPS[self._step_index](self.data))

    def go_back(self) -> None:
        """Go back to the previous step."""
        if self._step_index > 0:
            self._step_index -= 1
            self.switch_screen(self._STEPS[self._step_index](self.data))

    def action_quit_wizard(self) -> None:
        """Quit the wizard (Ctrl+Q)."""
        self.exit()


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #


def main():
    app = ArticleWizardApp()
    app.run()


if __name__ == "__main__":
    main()
