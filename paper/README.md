# AgentsX Research Paper (arXiv Submission Package)

This directory contains the camera-ready research paper for **AgentsX**, formatted for arXiv submission and top-tier software engineering / artificial intelligence conferences (ICSE / FSE / ASE / NeurIPS).

## Title
**AgentsX: A Resilient, Zero-Overhead, and Sandbox-Hardened Architecture for Autonomous Coding Agents**

## Files
- `main.tex`: Full camera-ready LaTeX source with all mathematical models, algorithm boxes (Algorithm2e), TikZ architecture diagrams, and empirical evaluation tables.
- `references.bib`: Complete BibTeX citations.

## Compilation Instructions

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
