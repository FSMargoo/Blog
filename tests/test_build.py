import tempfile
import textwrap
import unittest
from pathlib import Path

from build import BlogBuilder, LatexMacroError


class BlogBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = BlogBuilder()

    def test_math_heading_does_not_restart_parser(self):
        source = "## Distribution on $S^2$\n\nParagraph after heading.\n"

        result = self.builder._markdown_to_latex(source)

        self.assertEqual(result.count("Distribution"), 1)
        self.assertIn(r"\section{Distribution on $S^2$}", result)
        self.assertIn("Paragraph after heading.", result)

    def test_pdf_latex_inline_escapes_text_without_touching_math(self):
        source = r"C# uses 50% of a_b & keeps math $\frac{a_b}{c#}$."

        result = self.builder._latex_inline(source)

        self.assertIn(r"C\# uses 50\% of a\_b \& keeps math", result)
        self.assertIn(r"$\frac{a_b}{c#}$", result)

    def test_pdf_latex_inline_breaks_plain_urls(self):
        source = (
            "[https://github.com/FeatherCompute/LTC]"
            "(https://github.com/FeatherCompute/LTC)"
        )

        result = self.builder._latex_inline(source)

        self.assertEqual(result, r"\url{https://github.com/FeatherCompute/LTC}")

    def test_pdf_latex_images_emit_labels_for_references(self):
        source = r"![fig:demo|Caption $x$|width=120%](assets/a_b.png)"

        result = self.builder._latex_inline(source)

        self.assertIn(r"\includegraphics[width=1\linewidth,max width=\linewidth]", result)
        self.assertIn(r"{\detokenize{assets/a_b.png}}", result)
        self.assertIn(r"\caption{Caption $x$}", result)
        self.assertIn(r"\label{fig:demo}", result)

    def test_pdf_markdown_keeps_native_math_environments_raw(self):
        source = (
            "\\begin{equation}\n"
            "\\label{eq:csharp}\n"
            "x = y # z\n"
            "\\end{equation}\n"
            "\n"
            "C# outside math.\n"
        )

        result = self.builder._markdown_to_latex(source)

        self.assertIn("\\begin{equation}\n\\label{eq:csharp}\nx = y # z\n\\end{equation}", result)
        self.assertIn(r"C\# outside math.", result)

    def test_html_equations_are_not_nested_environments(self):
        source = (
            "before\n"
            "\\begin{equation}\n"
            "x=1 \\label{eq:x}\n"
            "\\end{equation}\n"
            "after\n"
        )

        result, labels = self.builder._preprocess_equations(source)

        self.assertNotIn("\\begin{equation}", result)
        self.assertIn("\\tag{1}", result)
        self.assertEqual(labels, {"x": 1})

    def test_relative_path_rewriter_leaves_external_schemes_alone(self):
        html = (
            '<a href="mailto:a@example.com">mail</a>'
            '<a href="/root.html">root</a>'
            '<img src="assets/image.png">'
        )

        result = self.builder._fix_relative_paths(html, "../")

        self.assertIn('href="mailto:a@example.com"', result)
        self.assertIn('href="/root.html"', result)
        self.assertIn('src="../assets/image.png"', result)

    def test_zhihu_equation_export_uses_display_math(self):
        source = (
            "before\n"
            "\\begin{equation}\n"
            "x=1 \\label{eq:x}\n"
            "\\end{equation}\n"
            "after [@eq:x]\n"
        )

        content, labels = self.builder._preprocess_equations_for_markdown(source)
        result = self.builder._process_numbered_refs_markdown(content, labels)

        self.assertNotIn("\\begin{equation}", result)
        self.assertIn("$$\nx=1\n\\tag{1}\n$$", result)
        self.assertIn("after 公式 1", result)

    def test_zhihu_citations_become_plain_reference_numbers(self):
        result = self.builder._replace_citations_plain_markdown(
            "Text [@a; @b] and [@missing].",
            {"a": 1, "b": 2},
        )

        self.assertIn("Text [1][2]", result)
        self.assertIn("[@missing]", result)

    def test_zhihu_figure_export_removes_custom_alt_features(self):
        source = "如[@fig:a]。\n\n![fig:a|Caption|width=50%](assets/a.png)"

        result = self.builder._process_numbered_refs_markdown(source)

        self.assertIn("如图 1。", result)
        self.assertIn("![图 1：Caption](../assets/a.png)", result)
        self.assertIn("图 1：Caption", result)
        self.assertNotIn("fig:a", result)
        self.assertNotIn("width=50%", result)

    def test_latex_macros_expand_only_inside_math_with_nested_braces(self):
        macros = self.builder._normalize_latex_macros({
            "esm": {
                "args": 1,
                "body": r"\left\langle #1\right\rangle",
            },
            "norm": {
                "args": 1,
                "body": r"\left\lVert #1\right\rVert",
            },
        })
        source = (
            r"Prose \esm{x} is untouched. "
            r"Math $\esm{\frac{a}{b}}$ and \(\norm{\esm{x}}\)."
        )

        result = self.builder._expand_latex_macros_in_markdown(source, macros, "test.md")

        self.assertIn(r"Prose \esm{x} is untouched", result)
        self.assertIn(r"$\left\langle \frac{a}{b}\right\rangle$", result)
        self.assertIn(
            r"\(\left\lVert \left\langle x\right\rangle\right\rVert\)",
            result,
        )

    def test_latex_macros_do_not_expand_inside_code(self):
        macros = self.builder._normalize_latex_macros({
            "esm": {
                "args": 1,
                "body": r"\left\langle #1\right\rangle",
            },
        })
        source = textwrap.dedent(r"""
            Inline code `$\esm{x}$`, real math $\esm{x}$.

            ```tex
            $\esm{x}$
            ```
        """).strip()

        result = self.builder._expand_latex_macros_in_markdown(source, macros, "test.md")

        self.assertIn(r"`$\esm{x}$`", result)
        self.assertIn(r"$\left\langle x\right\rangle$", result)
        self.assertIn("```tex\n$\\esm{x}$\n```", result)

    def test_latex_macro_arguments_require_balanced_braces(self):
        macros = self.builder._normalize_latex_macros({
            "esm": {
                "args": 1,
                "body": r"\left\langle #1\right\rangle",
            },
        })

        with self.assertRaisesRegex(LatexMacroError, r"\\esm expects argument 1"):
            self.builder._expand_latex_macros_in_markdown(r"$\esm$", macros, "test.md")

        with self.assertRaisesRegex(LatexMacroError, "unclosed macro argument group"):
            self.builder._expand_latex_macros_in_markdown(r"$\esm{x$", macros, "test.md")

    def test_latex_macro_cycle_detection_does_not_reject_nested_input(self):
        macros = self.builder._normalize_latex_macros({
            "wrap": {
                "args": 1,
                "body": r"[#1]",
            },
        })
        result = self.builder._expand_latex_macros_in_markdown(
            r"$\wrap{\wrap{x}}$",
            macros,
            "test.md",
        )
        self.assertEqual(result, "$[[x]]$")

        cyclic = self.builder._normalize_latex_macros({
            "a": {"args": 0, "body": r"\b"},
            "b": {"args": 0, "body": r"\a"},
        })
        with self.assertRaisesRegex(LatexMacroError, r"recursive LaTeX macro definitions"):
            self.builder._validate_latex_macro_cycles(cyclic, "test.md")

    def test_latex_macro_definitions_are_strict(self):
        with self.assertRaisesRegex(LatexMacroError, "reserved LaTeX command"):
            self.builder._normalize_latex_macros({
                "frac": {"args": 2, "body": r"#1/#2"},
            })

        with self.assertRaisesRegex(LatexMacroError, "references #2"):
            self.builder._normalize_latex_macros({
                "bad": {"args": 1, "body": r"#2"},
            })

        with self.assertRaisesRegex(LatexMacroError, "invalid macro name"):
            self.builder._normalize_latex_macros({
                "esm1": {"args": 1, "body": r"#1"},
            })

    def test_latex_macros_merge_global_and_local_without_shadowing(self):
        builder = BlogBuilder(skip_pdf=True)
        builder.config["latex_macros"] = {
            "R": {"args": 0, "body": r"\mathbb{R}"},
        }
        metadata = {
            "latex_macros": {
                "set": {"args": 1, "body": r"#1\in\R"},
            },
        }

        macros = builder._latex_macros_for_metadata(metadata, "test.md")
        result = builder._expand_latex_macros_in_markdown(r"$\set{x}$", macros, "test.md")

        self.assertEqual(result, r"$x\in\mathbb{R}$")

        with self.assertRaisesRegex(LatexMacroError, "duplicate macro definition"):
            builder._latex_macros_for_metadata({
                "latex_macros": {
                    "R": {"args": 0, "body": r"\mathbf{R}"},
                },
            }, "test.md")

    def test_latex_macros_flow_through_html_and_zhihu_pipelines(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder = BlogBuilder(skip_pdf=True)
            builder.content_dir = Path(tmp) / "content"
            posts_dir = builder.content_dir / "posts"
            posts_dir.mkdir(parents=True)
            path = posts_dir / "macro-test.md"
            path.write_text(textwrap.dedent(r"""
                ---
                title: 'Macro $\R$'
                date: '2026-01-01'
                latex_macros:
                  R:
                    args: 0
                    body: '\mathbb{R}'
                  esm:
                    args: 1
                    body: '\left\langle #1\right\rangle'
                ---

                Inline $\esm{x}$.

                \begin{equation}
                \label{eq:macro}
                \esm{\frac{a}{b}}
                \end{equation}

                See [@eq:macro].
            """).strip(), encoding="utf-8")

            post = builder._parse_markdown(path)
            zhihu = builder._post_to_zhihu_markdown(post)

        self.assertIn(r"\mathbb{R}", post["title"])
        self.assertIn(r"\left\langle x\right\rangle", post["body"])
        self.assertIn(r"\left\langle \frac{a}{b}\right\rangle", post["body"])
        self.assertIn(r"\left\langle \frac{a}{b}\right\rangle", zhihu)
        self.assertIn("公式 1", zhihu)


if __name__ == "__main__":
    unittest.main()
