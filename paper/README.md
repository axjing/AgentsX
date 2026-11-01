# AgentsX Research Paper (arXiv & Academic Publication Package)

This directory contains the camera-ready research paper package for **AgentsX**, formatted for arXiv submission and top-tier software engineering and artificial intelligence conferences (ICSE / FSE / ASE / NeurIPS).

## Title
**AgentsX: A Resilient, Zero-Overhead, and Sandbox-Hardened Runtime Harness for Autonomous Agents**  
*(《AgentsX: 一种面向自主智能体的高韧性、零开销且沙盒安全的系统级运行底座》)*

## Files in this Package
- `main.tex`: Full camera-ready LaTeX source (in English) with formal threat models, algebraic path definitions, Algorithm2e pseudocode, TikZ architecture diagrams, and comprehensive empirical evaluation tables.
- `paper_zh.md`: Full-length publication-grade Chinese preprint manuscript (中文完整学术论文稿件).
- `references.bib`: Complete BibTeX citations.

## Compilation Instructions (English LaTeX)

### Local Compilation (pdflatex / latexmk)
```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Or using `latexmk`:
```bash
latexmk -pdf main.tex
```

### Overleaf Submission
You can directly upload the `paper/` folder (`main.tex` and `references.bib`) to Overleaf. It compiles out-of-the-box using the standard `pdfLaTeX` compiler.

### arXiv Direct Submission
When submitting to arXiv:
1. Ensure `main.tex` and `references.bib` are in the submission root or tarball.
2. Select category: **cs.SE** (Computer Science - Software Engineering) as Primary, and **cs.AI** (Artificial Intelligence) as Secondary.
