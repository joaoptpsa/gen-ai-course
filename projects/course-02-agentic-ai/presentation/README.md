# Presentation

The project proposal deck, written in [Marp](https://marp.app) Markdown: `proposta.md` is the
source, `proposta.pdf` and `proposta.pptx` are rendered from it and committed.

## Render

```bash
bin/slides
```

It renders each `diagrams/*.mmd` to PNG with `mmdc`, then the deck to PDF and PPTX with `marp`.
Both come from mise (`npm:@mermaid-js/mermaid-cli`, `npm:@marp-team/marp-cli`). Marp drives an
installed Chrome or Chromium; set `CHROME_PATH` if it cannot find one.

## Edit

- Slides are separated by `---`; speaker notes are HTML comments and land in the PPTX notes.
- Live preview while editing: `marp --preview --allow-local-files proposta.md`, or the
  [Marp for VS Code](https://marketplace.visualstudio.com/items?itemName=marp-team.marp-vscode)
  extension.
- Diagrams are PNG, not SVG: Marp's browser clips Mermaid's SVG labels.

Syntax reference: <https://marpit.marp.app/markdown>
