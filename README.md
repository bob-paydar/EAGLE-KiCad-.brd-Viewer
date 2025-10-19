# EAGLE/KiCad `.brd` Viewer — Programmer: Bob Paydar
![Screenshot](https://github.com/bob-paydar/EAGLE-KiCad-.brd-Viewer/blob/main/Screenshot.png)
A lightweight PCB board viewer written in pure Python with Tkinter. It parses **EAGLE `.brd`** and **KiCad `.kicad_pcb`** files and renders layers, pads/SMDs, vias, polygons, texts, components, and nets. Includes project save/load, search, measuring, and export to **SVG** (built‑in) and **PNG** (via Pillow).

> **Note:** Altium binary `.PcbDoc` files are **not supported**. Export to a text format (e.g., IDF/ASCII) first if needed.

---

## Features

- Open **EAGLE** (`.brd`) and **KiCad** (`.kicad_pcb`) boards.  
- Layer list with per‑layer visibility toggles and standard palette/color mapping.  
- Components & Nets tabs with **live search**; clicking a component zooms to it; selecting a net highlights it.  
- Interactive canvas with **zoom, pan, grid**, and **measurement tool** (distance readout).  
- **Save/Load Project** (`.pvproj`) to persist file path, view, and UI state (layer visibility, searches).  
- **Export**:
  - **SVG**: always available, no extra deps.
  - **PNG**: requires Pillow (`pip install pillow`).  
- Text, polygon fill, circles/rectangles in packages, and mirrored/rotated element shape rendering.

---

## Requirements

- **Python** 3.8+ (tested on Windows; works cross‑platform where Tkinter is available)
- **Tkinter** (bundled with standard CPython installers on Windows/macOS; package `python3-tk` on some Linux distros)
- **Pillow** *(optional, only for PNG export)*

### Install (recommended)

```bash
# Optionally create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# Optional dependency for PNG export
pip install pillow
```

No other external packages are required.

---

## Run

```bash
python Brd_Viewer.py
```

Then use **Open .brd/.kicad_pcb** in the toolbar to load a board.

---

## UI Guide

### Toolbar
- **Open .brd/.kicad_pcb** — choose an EAGLE or KiCad board file.
- **Fit** — fit the whole board to the window.
- **Reset View** — reset zoom/offset to defaults.
- **Measure** (toggle) + **Clear Measure** — measure distances between points.
- **Save Project / Load Project** — persist and restore session state (`.pvproj`).
- **Export PNG / Export SVG** — export the current view (PNG requires Pillow).

### Sidebars
- **Layers** — scrollable list of layers with visibility checkboxes.
- **Components** — searchable list; selecting zooms and highlights the part.
- **Nets** — searchable list; selecting highlights all geometry on that net.

### Canvas & Controls
- **Mouse wheel** — zoom (also supports Linux Button‑4/5).  
- **Left‑drag** — place/drag measure points when Measure is enabled.  
- **Middle‑drag** — pan the view.  
- **Status bar** — shows zoom level and status messages.

---

## File Support Notes

- **EAGLE**: Parses layers, signals (wires, vias, polygons), elements and package shapes (wires, pads, SMDs, circles, rectangles, polygons), texts, with rotation/mirroring.  
- **KiCad**: Provides reasonable color mapping for common layers and supports zones/polygons where available.
- **Altium `.PcbDoc`**: Not supported (binary). Convert/export to a text format first.

---

## Known Limitations

- Rotated text in PNG export is not applied (Pillow’s basic `ImageDraw` has no rotated text API without extra fonts/transform tricks). SVG export includes text rotation.
- Units are as provided in the file; measurement readout uses the same units.

---

## Troubleshooting

- **PNG export fails** → Install Pillow:
  ```bash
  pip install pillow
  ```
- **Tkinter not found** on Linux → install your distro’s Tk package (e.g., `sudo apt install python3-tk`).

---

## License

MIT (or project’s default; update as desired).

---

## Credits

- Original code and UI: **Bob Paydar**.

