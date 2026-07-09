# LaTeX-Style Academic Blog Generator

一个将 Markdown 编译为 **LaTeX 级别排版**的静态博客生成器。

**设计灵感**：首页排版参考 *Nature* 期刊网站（大图 Hero + 卡片网格），文章内页保持学术论文的严谨美感，同时支持**亮/暗双主题**与**Banner 头图**。

---

## 特性

- **Nature 风首页**：Featured 大图头版 + 响应式文章卡片网格（带图片、分类、摘要）
- **亮/暗双主题**：支持手动切换（右下角按钮）与跟随系统偏好，切换无闪烁
- **Banner 头图**：每篇文章可在 frontmatter 中设置专属 banner，首页卡片和文章页顶部自动展示
- **LaTeX 级论文排版**：衬线字体、两端对齐、首行缩进、Booktabs 表格、Abstract 摘要框
- **数学公式**：KaTeX 支持 `$...$` / `$$...$$`
- **目录自动生成**：可折叠的 Table of Contents
- **标签 & 分类 & 归档**：完整的 tag / category / archive 页面，带缩略图列表
- **RSS 订阅**：自动生成 `feed.xml`
- **代码高亮**：Pygments 语法高亮
- **参考文献**：frontmatter 定义 bibliography，自动渲染编号列表
- **响应式布局**：完美适配桌面与手机
- **自定义 LaTeX 数学宏**：支持构建阶段展开的 `latex_macros`，HTML / PDF / 知乎导出保持一致

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

如需生成文章 PDF，请另外安装包含 `xelatex` 的 TeX Live / MacTeX。

### 2. 写文章

在 `content/posts/` 下新建 `.md`，顶部写 YAML frontmatter：

```markdown
---
title: "你的论文标题"
date: "2024-05-01"
banner: "assets/images/your-banner.jpg"   # ← 头图路径（相对站点根目录）
authors:
  - name: "张三"
    affiliation: "某某大学"
    email: "zhang@example.edu"
abstract: |
  这里是摘要。如果包含 LaTeX 反斜杠，建议用 | 字面量块。
keywords: ["关键词1", "关键词2"]
tags: ["Tag1", "Tag2"]
category: "研究分类"
doi: "10.1234/example.2024.001"
bibliography:
  - "作者. (年份). 标题. 期刊."
---

## 1 Introduction

正文支持 Markdown、数学公式 $E=mc^2$：

$$
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
$$

```python
def hello():
    print("Hello!")
```
```

> **关于 banner**：推荐尺寸 **1200×400 px**（文章页横幅）或 **1200×675 px**（16:9 卡片图）。图片放在 `content/assets/images/`，frontmatter 中路径写 `assets/images/xxx.png`（无需加 `content/` 前缀）。

### 自定义 LaTeX 数学宏

可在 `config.yaml` 中定义全局宏，或在单篇文章 frontmatter 中定义局部宏：

```yaml
latex_macros:
  esm:
    args: 1
    body: '\left\langle #1\right\rangle'
  R:
    args: 0
    body: '\mathbb{R}'
```

正文中只在数学区域展开，例如 `$\esm{x}\in\R$` 会在构建时变成标准 LaTeX。代码块、行内代码和普通正文中的 `\esm{x}` 不会被替换。

### 3. 编译

```bash
python build.py
```

生成结果在 `public/` 目录中。

### 4. 预览

```bash
python serve.py --watch
```

浏览器打开 http://localhost:8000。`--watch` 会在内容、模板或静态资源变化后自动重新构建。

### 5. 测试

```bash
python -m unittest discover -v
```

---

## 项目结构

```
.
├── build.py              # 构建脚本（核心）
├── config.yaml           # 博客全局配置
├── requirements.txt      # Python 依赖
├── README.md             # 本文档
│
├── content/
│   ├── posts/            # 博文 Markdown
│   ├── pages/            # 独立页面（如 About）
│   └── assets/images/    # 图片等资源（banner 放这里）
│
├── templates/            # Jinja2 HTML 模板
├── static/css/style.css  # 主题样式（亮/暗双主题）
└── public/               # 生成的站点（编译后）
```

---

## 配置说明

编辑 `config.yaml`：

| 字段 | 说明 |
|------|------|
| `site_name` | 博客名称 |
| `journal.name` | 期刊名（显示在顶部导航） |
| `journal.issn` | ISSN 号 |
| `author` | 默认作者（页脚版权） |
| `base_url` | 部署地址（RSS 使用） |
| `posts_per_page` | 首页文章数 |

---

## Frontmatter 完整字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `title` | ✅ | 标题 |
| `date` | ✅ | `YYYY-MM-DD` |
| `banner` | ❌ | 头图路径，如 `assets/images/banner.png` |
| `authors` | ❌ | 列表，每项含 `name`, `affiliation`, `email` |
| `abstract` | ❌ | 摘要（含 LaTeX 反斜杠建议用 `\|` 块） |
| `keywords` | ❌ | 关键词列表 |
| `category` | ❌ | 分类 |
| `tags` | ❌ | 标签列表 |
| `doi` | ❌ | DOI 号 |
| `bibliography` | ❌ | 参考文献字符串列表 |
| `latex_macros` | ❌ | 单篇文章的自定义数学宏 |
| `draft` | ❌ | `true` 则不生成 |
| `slug` | ❌ | 自定义 URL 别名 |

---

## 主题切换

- 点击右下角 **🌙 / ☀️** 按钮可在亮/暗主题间切换
- 偏好会保存到 `localStorage`，下次访问自动恢复
- 首次访问时自动跟随系统 `prefers-color-scheme`
- 切换过程平滑过渡，无闪烁

---

## 部署

`public/` 是纯静态文件，可直接部署到：

- **GitHub Pages**
- **Vercel / Netlify**
- **Nginx / Apache / OSS / S3**

如果部署到子目录，修改 `config.yaml` 中的 `base_url`。

---

## License

MIT
