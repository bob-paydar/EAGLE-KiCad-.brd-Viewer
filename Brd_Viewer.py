#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EAGLE .brd Viewer — Minimal, no external deps (Tkinter)
Author: Bob Paydar
Updated: Added scrolling for layers/components, full pad/SMD drawing, PNG/SVG export (PNG requires Pillow), KiCad support (Altium binary not supported).
Further Updated: Added polygon and text parsing/rendering, pad/SMD rotation, standard layer colors, net highlighting, modern UI with ttk theme, clear measure button, component/net tabs.
Further Fixed: Removed invalid layer check for vias in highlight to fix AttributeError.
Further Enhanced: Parse component shapes from libraries and packages, render rotated pads/SMDs for elements, highlight selected component shapes, handle wires in packages.
Further Fixed: Corrected indentation in _draw_element_shapes and _add_pad_from_xml to fix IndentationError and SyntaxError.
Further Improved: Added polygon fill for copper pours, added support for circles and rectangles in EAGLE packages, added polygon in packages, added zone parsing for KiCad, added fill for gr_poly if specified.
Further Fixed: Corrected mirror transformation to flip over Y-axis (x = -x) instead of X-axis for EAGLE components.
Further Fixed: Lighten fill color for polygons to make traces visible, expanded bounds to include component shapes.
Further Fixed: Added _parse_rot to parsers to fix attribute error.
"""

import json
import math
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Union

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ------------------------------
# Data structures
# ------------------------------

@dataclass
class Layer:
    number: int
    name: str
    color: int = 7
    visible: bool = True
    active: bool = True

@dataclass
class Wire:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    layer: int
    kind: str = "plain"  # "plain" or "signal"
    net: str = ""

@dataclass
class Via:
    x: float
    y: float
    drill: float = 0.0
    diameter: float = 0.0
    extent: str = ""
    net: str = ""

@dataclass
class Pad:
    name: str
    x: float
    y: float
    drill: float = 0.0
    diameter: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    shape: str = "round"
    layer: int = 0
    rot: float = 0.0

@dataclass
class SMD:
    name: str
    x: float
    y: float
    dx: float = 0.0
    dy: float = 0.0
    layer: int = 0
    roundness: float = 0.0
    rot: float = 0.0

@dataclass
class Circle:
    x: float
    y: float
    radius: float
    width: float
    layer: int

@dataclass
class Rect:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: int
    rot: float = 0.0

@dataclass
class Element:
    name: str
    value: str
    library: str
    package: str
    x: float
    y: float
    rot: str = ""

@dataclass
class Polygon:
    vertices: List[Tuple[float, float]]
    layer: int
    width: float
    net: str = ""
    fill: bool = False
    is_outline: bool = False

@dataclass
class Text:
    x: float
    y: float
    text: str
    layer: int
    size: float = 1.0
    rot: float = 0.0

@dataclass
class Board:
    layers: Dict[int, Layer] = field(default_factory=dict)
    wires: List[Wire] = field(default_factory=list)
    vias: List[Via] = field(default_factory=list)
    pads: List[Pad] = field(default_factory=list)
    smds: List[SMD] = field(default_factory=list)
    elements: List[Element] = field(default_factory=list)
    polygons: List[Polygon] = field(default_factory=list)
    texts: List[Text] = field(default_factory=list)
    packages: Dict[str, List[Union[Wire, Pad, SMD, Circle, Rect, Polygon]]] = field(default_factory=dict)  # Package shapes
    bounds: Optional[Tuple[float, float, float, float]] = None

# ------------------------------
# Parser for EAGLE XML .brd
# ------------------------------
class EagleParser:
    def __init__(self, path: str):
        self.path = path
        self.tree = None
        self.root = None
        self.board = Board()

    def parse(self) -> Board:
        try:
            self.tree = ET.parse(self.path)
            self.root = self.tree.getroot()
        except ET.ParseError as e:
            raise RuntimeError(f"XML parse error: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to open file: {e}")

        drawing = self.root.find('drawing')
        if drawing is None:
            raise RuntimeError("Not an EAGLE XML file (missing <drawing> root)")
        brd = drawing.find('board')
        if brd is None:
            raise RuntimeError("Not a board file (missing <board> element)")

        self._parse_layers(drawing)
        self._parse_libraries(brd)  # Parse packages from libraries
        self._parse_plain(brd)
        self._parse_elements(brd)
        self._parse_signals(brd)
        self._compute_bounds()
        return self.board

    def _parse_layers(self, drawing):
        layers = drawing.find('layers')
        if layers is None:
            return
        for l in layers.findall('layer'):
            try:
                num = int(l.get('number', '0'))
                name = l.get('name', f"L{num}")
                color = int(l.get('color', '7'))
                visible = l.get('visible', 'yes') == 'yes'
                active = l.get('active', 'yes') == 'yes'
                self.board.layers[num] = Layer(number=num, name=name, color=color, visible=visible, active=active)
            except Exception:
                continue

    def _parse_libraries(self, brd):
        libraries = brd.find('libraries')
        if libraries is None:
            return
        for lib in libraries.findall('library'):
            packages = lib.find('packages')
            if packages is None:
                continue
            for pkg in packages.findall('package'):
                pkg_name = pkg.get('name', '')
                shapes = []
                for w in pkg.findall('wire'):
                    w_obj = self._add_wire_from_xml(w, kind="package")
                    if w_obj:
                        shapes.append(w_obj)
                for pad in pkg.findall('pad'):
                    pad_obj = self._add_pad_from_xml(pad)
                    if pad_obj:
                        shapes.append(pad_obj)
                for smd in pkg.findall('smd'):
                    smd_obj = self._add_smd_from_xml(smd)
                    if smd_obj:
                        shapes.append(smd_obj)
                for c in pkg.findall('circle'):
                    c_obj = self._add_circle_from_xml(c)
                    if c_obj:
                        shapes.append(c_obj)
                for r in pkg.findall('rectangle'):
                    r_obj = self._add_rect_from_xml(r)
                    if r_obj:
                        shapes.append(r_obj)
                for poly in pkg.findall('polygon'):
                    p_obj = self._add_polygon_from_xml(poly, net="", in_package=True)
                    if p_obj:
                        shapes.append(p_obj)
                self.board.packages[pkg_name] = shapes

    def _parse_plain(self, brd):
        plain = brd.find('plain')
        if plain is None:
            return
        for w in plain.findall('wire'):
            self._add_wire_from_xml(w, kind="plain")
        for p in plain.findall('pad'):
            self._add_pad_from_xml(p)
        for s in plain.findall('smd'):
            self._add_smd_from_xml(s)
        for poly in plain.findall('polygon'):
            self._add_polygon_from_xml(poly, net="")
        for text in plain.findall('text'):
            self._add_text_from_xml(text)

    def _parse_elements(self, brd):
        elements = brd.find('elements')
        if elements is None:
            return
        for e in elements.findall('element'):
            try:
                name = e.get('name', '')
                value = e.get('value', '')
                library = e.get('library', '')
                package = e.get('package', '')
                x = float(e.get('x', '0'))
                y = float(e.get('y', '0'))
                rot = e.get('rot', '')
                self.board.elements.append(Element(name=name, value=value, library=library, package=package, x=x, y=y, rot=rot))
            except Exception:
                continue

    def _parse_signals(self, brd):
        signals = brd.find('signals')
        if signals is None:
            return
        for s in signals.findall('signal'):
            name = s.get('name', '')
            for w in s.findall('wire'):
                w_obj = self._add_wire_from_xml(w, kind="signal")
                if w_obj:
                    w_obj.net = name
            for v in s.findall('via'):
                self._add_via_from_xml(v, name)
            for poly in s.findall('polygon'):
                self._add_polygon_from_xml(poly, net=name)

    def _add_wire_from_xml(self, w_el, kind: str) -> Optional[Wire]:
        try:
            x1 = float(w_el.get('x1', '0'))
            y1 = float(w_el.get('y1', '0'))
            x2 = float(w_el.get('x2', '0'))
            y2 = float(w_el.get('y2', '0'))
            width = float(w_el.get('width', '0.1'))
            layer = int(w_el.get('layer', '0'))
            w = Wire(x1=x1, y1=y1, x2=x2, y2=y2, width=width, layer=layer, kind=kind)
            self.board.wires.append(w)
            return w
        except Exception:
            pass
        return None

    def _add_via_from_xml(self, v_el, net: str):
        try:
            x = float(v_el.get('x', '0'))
            y = float(v_el.get('y', '0'))
            drill = float(v_el.get('drill', '0'))
            diameter = float(v_el.get('diameter', '0')) if v_el.get('diameter') else 0.0
            extent = v_el.get('extent', '')
            v = Via(x=x, y=y, drill=drill, diameter=diameter, extent=extent, net=net)
            self.board.vias.append(v)
        except Exception:
            pass

    def _add_pad_from_xml(self, p_el) -> Optional[Pad]:
        try:
            name = p_el.get('name', '')
            x = float(p_el.get('x', '0'))
            y = float(p_el.get('y', '0'))
            drill = float(p_el.get('drill', '0'))
            diameter = float(p_el.get('diameter', '0'))
            shape = p_el.get('shape', 'round')
            layer = int(p_el.get('layer', '0'))
            rot_str = p_el.get('rot', 'R0')
            rot = float(rot_str.lstrip('R').lstrip('M'))
            dx = diameter if shape != 'round' else 0.0
            dy = diameter if shape != 'round' else 0.0
            p = Pad(name=name, x=x, y=y, drill=drill, diameter=diameter, dx=dx, dy=dy, shape=shape, layer=layer, rot=rot)
            self.board.pads.append(p)
            return p
        except Exception:
            pass
        return None

    def _add_smd_from_xml(self, s_el) -> Optional[SMD]:
        try:
            name = s_el.get('name', '')
            x = float(s_el.get('x', '0'))
            y = float(s_el.get('y', '0'))
            dx = float(s_el.get('dx', '0'))
            dy = float(s_el.get('dy', '0'))
            layer = int(s_el.get('layer', '0'))
            roundness = float(s_el.get('roundness', '0'))
            rot_str = s_el.get('rot', 'R0')
            rot = float(rot_str.lstrip('R').lstrip('M'))
            s = SMD(name=name, x=x, y=y, dx=dx, dy=dy, layer=layer, roundness=roundness, rot=rot)
            self.board.smds.append(s)
            return s
        except Exception:
            pass
        return None

    def _add_circle_from_xml(self, c_el) -> Optional[Circle]:
        try:
            x = float(c_el.get('x', '0'))
            y = float(c_el.get('y', '0'))
            radius = float(c_el.get('radius', '0'))
            width = float(c_el.get('width', '0.1'))
            layer = int(c_el.get('layer', '0'))
            return Circle(x=x, y=y, radius=radius, width=width, layer=layer)
        except Exception:
            pass
        return None

    def _add_rect_from_xml(self, r_el) -> Optional[Rect]:
        try:
            x1 = float(r_el.get('x1', '0'))
            y1 = float(r_el.get('y1', '0'))
            x2 = float(r_el.get('x2', '0'))
            y2 = float(r_el.get('y2', '0'))
            layer = int(r_el.get('layer', '0'))
            rot_str = r_el.get('rot', 'R0')
            rot = float(rot_str.lstrip('R').lstrip('M'))
            return Rect(x1=x1, y1=y1, x2=x2, y2=y2, layer=layer, rot=rot)
        except Exception:
            pass
        return None

    def _add_polygon_from_xml(self, p_el, net: str, in_package: bool = False) -> Optional[Polygon]:
        try:
            layer = int(p_el.get('layer', '0'))
            width = float(p_el.get('width', '0.1'))
            verts = []
            for v in p_el.findall('vertex'):
                vx = float(v.get('x', '0'))
                vy = float(v.get('y', '0'))
                verts.append((vx, vy))
            if len(verts) > 2:
                is_outline = (layer == 20)
                fill = (net != "") and not is_outline
                p = Polygon(vertices=verts, layer=layer, width=width, net=net, fill=fill, is_outline=is_outline)
                if in_package:
                    return p
                else:
                    self.board.polygons.append(p)
                    return p
        except Exception:
            pass
        return None

    def _add_text_from_xml(self, t_el):
        try:
            x = float(t_el.get('x', '0'))
            y = float(t_el.get('y', '0'))
            layer = int(t_el.get('layer', '0'))
            size = float(t_el.get('size', '1.27'))
            rot_str = t_el.get('rot', 'R0')
            rot = float(rot_str.lstrip('R').lstrip('M'))
            text = t_el.text or ''
            self.board.texts.append(Text(x=x, y=y, text=text, layer=layer, size=size, rot=rot))
        except Exception:
            pass

    def _parse_rot(self, rot_str: str) -> float:
        if not rot_str:
            return 0.0
        mirror = rot_str[0] == 'M'
        rot_str = rot_str.lstrip('M')
        rot = float(rot_str.lstrip('R')) if rot_str else 0.0
        if mirror:
            rot = -rot
        return rot

    def _compute_bounds(self):
        xs, ys = [], []
        for w in self.board.wires:
            xs += [w.x1, w.x2]
            ys += [w.y1, w.y2]
        for v in self.board.vias:
            xs.append(v.x)
            ys.append(v.y)
        for p in self.board.pads:
            xs.append(p.x)
            ys.append(p.y)
        for s in self.board.smds:
            xs.append(s.x)
            ys.append(s.y)
        for e in self.board.elements:
            xs.append(e.x)
            ys.append(e.y)
            package_shapes = self.board.packages.get(e.package, [])
            angle = math.radians(self._parse_rot(e.rot))
            mirror = 'M' in e.rot
            for shape in package_shapes:
                if isinstance(shape, Wire):
                    rx1 = shape.x1 if not mirror else -shape.x1
                    ry1 = shape.y1
                    rx1_rot = rx1 * math.cos(angle) - ry1 * math.sin(angle)
                    ry1_rot = rx1 * math.sin(angle) + ry1 * math.cos(angle)
                    abs_x1 = e.x + rx1_rot
                    abs_y1 = e.y + ry1_rot

                    rx2 = shape.x2 if not mirror else -shape.x2
                    ry2 = shape.y2
                    rx2_rot = rx2 * math.cos(angle) - ry2 * math.sin(angle)
                    ry2_rot = rx2 * math.sin(angle) + ry2 * math.cos(angle)
                    abs_x2 = e.x + rx2_rot
                    abs_y2 = e.y + ry2_rot

                    xs += [abs_x1, abs_x2]
                    ys += [abs_y1, abs_y2]
                elif isinstance(shape, (Pad, SMD, Circle)):
                    rx = shape.x if not mirror else -shape.x
                    ry = shape.y
                    rx_rot = rx * math.cos(angle) - ry * math.sin(angle)
                    ry_rot = rx * math.sin(angle) + ry * math.cos(angle)
                    abs_x = e.x + rx_rot
                    abs_y = e.y + ry_rot
                    xs.append(abs_x)
                    ys.append(abs_y)
                elif isinstance(shape, Rect):
                    x1 = shape.x1 if not mirror else -shape.x1
                    y1 = shape.y1
                    x2 = shape.x2 if not mirror else -shape.x2
                    y2 = shape.y2
                    xs_rel = [x1, x2]
                    ys_rel = [y1, y2]
                    for rx, ry in [(min(xs_rel), min(ys_rel)), (min(xs_rel), max(ys_rel)), (max(xs_rel), min(ys_rel)), (max(xs_rel), max(ys_rel))]:
                        rx_rot = rx * math.cos(angle) - ry * math.sin(angle)
                        ry_rot = rx * math.sin(angle) + ry * math.cos(angle)
                        abs_x = e.x + rx_rot
                        abs_y = e.y + ry_rot
                        xs.append(abs_x)
                        ys.append(abs_y)
                elif isinstance(shape, Polygon):
                    for vx, vy in shape.vertices:
                        rx = vx if not mirror else -vx
                        ry = vy
                        rx_rot = rx * math.cos(angle) - ry * math.sin(angle)
                        ry_rot = rx * math.sin(angle) + ry * math.cos(angle)
                        abs_x = e.x + rx_rot
                        abs_y = e.y + ry_rot
                        xs.append(abs_x)
                        ys.append(abs_y)
        for poly in self.board.polygons:
            for vx, vy in poly.vertices:
                xs.append(vx)
                ys.append(vy)
        if xs and ys:
            self.board.bounds = (min(xs), min(ys), max(xs), max(ys))
        else:
            self.board.bounds = (0.0, 0.0, 100.0, 100.0)

# ------------------------------
# Viewer UI
# ------------------------------
class BRDViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EAGLE/KiCad .brd Viewer — Programmer: Bob Paydar")
        self.geometry("1200x800")
        self.minsize(900, 600)

        self.style = ttk.Style()
        self.style.theme_use('clam')

        self.board: Optional[Board] = None
        self.file_path: Optional[str] = None
        self.scale = 5.0
        self.offset_x = 100.0
        self.offset_y = 100.0

        self.layer_checks: Dict[int, tk.BooleanVar] = {}
        self.measure_mode = tk.BooleanVar(value=False)
        self.measure_points: List[Tuple[float, float]] = []
        self.selected_element: Optional[Element] = None
        self.selected_net: Optional[str] = None

        self._build_ui()
        self._bind_canvas_events()

    # ----- UI layout -----
    def _build_ui(self):
        # Toolbar
        tb = ttk.Frame(self)
        tb.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(tb, text="Open .brd/.kicad_pcb", command=self.open_brd).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(tb, text="Fit", command=self.fit_to_view).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Reset View", command=self.reset_view).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(tb, text="Measure", variable=self.measure_mode).pack(side=tk.LEFT, padx=12)
        ttk.Button(tb, text="Clear Measure", command=self.clear_measure).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Save Project", command=self.save_project).pack(side=tk.LEFT, padx=12)
        ttk.Button(tb, text="Load Project", command=self.load_project).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Export PNG", command=self.export_png).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="Export SVG", command=self.export_svg).pack(side=tk.LEFT, padx=4)

        # Main area: left sidebar + canvas + right sidebar
        main = ttk.Frame(self)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Left: Layers (scrollable)
        left = ttk.Frame(main, width=220)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        ttk.Label(left, text="Layers", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        layer_container = ttk.Frame(left)
        layer_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.layer_canvas = tk.Canvas(layer_container, borderwidth=0, highlightthickness=0)
        vbar = tk.Scrollbar(layer_container, orient=tk.VERTICAL, command=self.layer_canvas.yview)
        self.layer_canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.layer_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.layer_inner = ttk.Frame(self.layer_canvas)
        self.layer_canvas.create_window((0, 0), window=self.layer_inner, anchor="nw")
        self.layer_inner.bind('<Configure>', lambda e: self.layer_canvas.configure(scrollregion=self.layer_canvas.bbox("all")))

        # Center: Canvas
        center = ttk.Frame(main)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(center, bg="#101015", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Right: Tabs for Components and Nets
        right = ttk.Frame(main, width=280)
        right.pack(side=tk.LEFT, fill=tk.Y)
        right.pack_propagate(False)

        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Components tab
        comp_frame = ttk.Frame(notebook)
        notebook.add(comp_frame, text="Components")
        srch_row = ttk.Frame(comp_frame)
        srch_row.pack(fill=tk.X)
        ttk.Label(srch_row, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        e = ttk.Entry(srch_row, textvariable=self.search_var)
        e.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        e.bind('<KeyRelease>', self._on_search)
        self.comp_list = tk.Listbox(comp_frame, exportselection=False)
        comp_scrollbar = tk.Scrollbar(comp_frame, orient="vertical", command=self.comp_list.yview)
        self.comp_list.configure(yscrollcommand=comp_scrollbar.set)
        self.comp_list.pack(side="left", fill="both", expand=True)
        comp_scrollbar.pack(side="right", fill="y")
        self.comp_list.bind('<<ListboxSelect>>', self._on_component_select)

        # Nets tab
        net_frame = ttk.Frame(notebook)
        notebook.add(net_frame, text="Nets")
        net_srch_row = ttk.Frame(net_frame)
        net_srch_row.pack(fill=tk.X)
        ttk.Label(net_srch_row, text="Search:").pack(side=tk.LEFT)
        self.net_search_var = tk.StringVar()
        ne = ttk.Entry(net_srch_row, textvariable=self.net_search_var)
        ne.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ne.bind('<KeyRelease>', self._on_net_search)
        self.net_list = tk.Listbox(net_frame, exportselection=False)
        net_scrollbar = tk.Scrollbar(net_frame, orient="vertical", command=self.net_list.yview)
        self.net_list.configure(yscrollcommand=net_scrollbar.set)
        self.net_list.pack(side="left", fill="both", expand=True)
        net_scrollbar.pack(side="right", fill="y")
        self.net_list.bind('<<ListboxSelect>>', self._on_net_select)

        # Status bar
        sb = ttk.Frame(self)
        sb.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_lbl = ttk.Label(sb, text="Ready")
        self.status_lbl.pack(side=tk.LEFT, padx=6)
        self.zoom_lbl = ttk.Label(sb, text="Zoom: 100%")
        self.zoom_lbl.pack(side=tk.RIGHT, padx=6)

    def _bind_canvas_events(self):
        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.canvas.bind('<Motion>', self._on_mouse_move)
        self.canvas.bind('<ButtonPress-1>', self._on_left_down)
        self.canvas.bind('<B1-Motion>', self._on_left_drag)
        self.canvas.bind('<MouseWheel>', self._on_mouse_wheel)           # Windows
        self.canvas.bind('<Button-4>', self._on_mouse_wheel)             # Linux scroll up
        self.canvas.bind('<Button-5>', self._on_mouse_wheel)             # Linux scroll down

        # Middle mouse to pan as well
        self.canvas.bind('<ButtonPress-2>', self._on_mid_down)
        self.canvas.bind('<B2-Motion>', self._on_mid_drag)

        self._drag_start = None

    # ----- File ops -----
    def open_brd(self):
        path = filedialog.askopenfilename(title='Open PCB File', filetypes=[('EAGLE Board', '*.brd'), ('KiCad PCB', '*.kicad_pcb'), ('Altium PCB', '*.PcbDoc'), ('All Files', '*.*')])
        if not path:
            return
        try:
            if path.lower().endswith('.kicad_pcb'):
                parser = KicadParser(path)
            elif path.lower().endswith('.brd'):
                parser = EagleParser(path)
            elif path.lower().endswith('.pcbdoc'):
                raise RuntimeError("Altium .PcbDoc is binary format; not supported. Export to text or IDF if possible.")
            else:
                raise RuntimeError("Unsupported file format. Only .brd and .kicad_pcb supported.")
            board = parser.parse()
        except Exception as e:
            messagebox.showerror("Open failed", str(e))
            return

        self.board = board
        self.file_path = path
        self._populate_layers()
        self._populate_components()
        self._populate_nets()
        self.fit_to_view()
        self.redraw()
        self.status_lbl.config(text=f"Loaded: {os.path.basename(path)}")

    def export_png(self):
        if not self.board:
            messagebox.showinfo("Export", "Open a file first.")
            return
        if not PIL_AVAILABLE:
            messagebox.showerror("Export PNG", "Pillow not installed. Run: pip install pillow")
            return
        path = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG Image', '*.png')])
        if not path:
            return
        self._export_to_image(path, 'png')

    def export_svg(self):
        if not self.board:
            messagebox.showinfo("Export", "Open a file first.")
            return
        path = filedialog.asksaveasfilename(defaultextension='.svg', filetypes=[('SVG Image', '*.svg')])
        if not path:
            return
        self._export_to_svg(path)

    def _export_to_image(self, path: str, fmt: str):
        visible_layers = {num for num, var in self.layer_checks.items() if var.get()}
        minx, miny, maxx, maxy = self.board.bounds or (0, 0, 100, 100)
        w_board = maxx - minx or 1
        h_board = maxy - miny or 1
        width, height = 2000, 2000
        img_scale = min((width - 100) / w_board, (height - 100) / h_board)
        ox = (width - w_board * img_scale) / 2
        oy = (height - h_board * img_scale) / 2

        def world_to_img(x: float, y: float) -> Tuple[float, float]:
            ix = ox + (x - minx) * img_scale
            iy = oy + (maxy - y) * img_scale
            return ix, iy

        img = Image.new('RGB', (width, height), color=(16, 16, 21))
        draw = ImageDraw.Draw(img)

        # Polygons
        for p in self.board.polygons:
            if p.layer not in visible_layers:
                continue
            color_str = self._layer_color(p.layer)
            color = self._color_to_rgb(self._lighten_color(color_str)) if p.fill else self._color_to_rgb(color_str)
            points = [world_to_img(vx, vy) for vx, vy in p.vertices]
            line_width = int(max(1.0, p.width * img_scale))
            draw.polygon(points, fill=color if p.fill else None, outline=self._color_to_rgb(color_str), width=line_width)

        # Wires
        for w in self.board.wires:
            if w.layer not in visible_layers:
                continue
            color = self._color_to_rgb(self._layer_color(w.layer))
            ix1, iy1 = world_to_img(w.x1, w.y1)
            ix2, iy2 = world_to_img(w.x2, w.y2)
            line_width = int(max(1.0, w.width * img_scale))
            draw.line([ix1, iy1, ix2, iy2], fill=color, width=line_width)

        # Pads
        for p in self.board.pads:
            if p.layer not in visible_layers:
                continue
            color = self._color_to_rgb(self._layer_color(p.layer))
            ix, iy = world_to_img(p.x, p.y)
            angle = math.radians(p.rot)
            if p.shape != 'round' and p.dx > 0 and p.dy > 0:
                hw = p.dx * img_scale / 2
                hh = p.dy * img_scale / 2
                points = [
                    (hw * math.cos(angle) - hh * math.sin(angle), hw * math.sin(angle) + hh * math.cos(angle)),
                    (hw * math.cos(angle) + hh * math.sin(angle), hw * math.sin(angle) - hh * math.cos(angle)),
                    (-hw * math.cos(angle) + hh * math.sin(angle), -hw * math.sin(angle) - hh * math.cos(angle)),
                    (-hw * math.cos(angle) - hh * math.sin(angle), -hw * math.sin(angle) + hh * math.cos(angle)),
                ]
                rotated_points = [(ix + px, iy + py) for px, py in points]
                draw.polygon(rotated_points, outline=color, width=1)
            else:
                r = max(p.diameter, 0.1) * img_scale / 2
                draw.ellipse([ix - r, iy - r, ix + r, iy + r], outline=color, width=1)
            if p.drill > 0:
                dr = p.drill * img_scale / 2
                draw.ellipse([ix - dr, iy - dr, ix + dr, iy + dr], fill='white')

        # SMDs
        for s in self.board.smds:
            if s.layer not in visible_layers:
                continue
            color = self._color_to_rgb(self._layer_color(s.layer))
            ix, iy = world_to_img(s.x, s.y)
            angle = math.radians(s.rot)
            hw = s.dx * img_scale / 2
            hh = s.dy * img_scale / 2
            points = [
                (hw * math.cos(angle) - hh * math.sin(angle), hw * math.sin(angle) + hh * math.cos(angle)),
                (hw * math.cos(angle) + hh * math.sin(angle), hw * math.sin(angle) - hh * math.cos(angle)),
                (-hw * math.cos(angle) + hh * math.sin(angle), -hw * math.sin(angle) - hh * math.cos(angle)),
                (-hw * math.cos(angle) - hh * math.sin(angle), -hw * math.sin(angle) + hh * math.cos(angle)),
            ]
            rotated_points = [(ix + px, iy + py) for px, py in points]
            draw.polygon(rotated_points, fill=color, outline=color, width=1)

        # Vias
        for v in self.board.vias:
            ix, iy = world_to_img(v.x, v.y)
            r = max(v.diameter or 0, v.drill or 0.1) * img_scale / 2
            draw.ellipse([ix - r, iy - r, ix + r, iy + r], outline='white', width=1)
            if v.drill > 0:
                dr = v.drill * img_scale / 2
                draw.ellipse([ix - dr, iy - dr, ix + dr, iy + dr], fill='white')

        # Texts
        for t in self.board.texts:
            if t.layer not in visible_layers:
                continue
            color = self._color_to_rgb(self._layer_color(t.layer))
            ix, iy = world_to_img(t.x, t.y)
            font_size = int(t.size * img_scale)
            draw.text((ix, iy), t.text, fill=color, font_size=font_size)  # no rotation in PIL draw.text

        # Elements (markers only)
        for e in self.board.elements:
            ix, iy = world_to_img(e.x, e.y)
            size_px = 6
            draw.line((ix - size_px, iy, ix + size_px, iy), fill='gray', width=1)
            draw.line((ix, iy - size_px, ix, iy + size_px), fill='gray', width=1)

        img.save(path, format=fmt.upper())
        self.status_lbl.config(text=f"Exported {fmt.upper()}: {os.path.basename(path)}")

    def _export_to_svg(self, path: str):
        visible_layers = {num for num, var in self.layer_checks.items() if var.get()}
        minx, miny, maxx, maxy = self.board.bounds or (0, 0, 100, 100)
        w_board = maxx - minx or 1
        h_board = maxy - miny or 1
        width, height = 2000, 2000
        img_scale = min((width - 100) / w_board, (height - 100) / h_board)
        ox = (width - w_board * img_scale) / 2
        oy = (height - h_board * img_scale) / 2

        def world_to_img(x: float, y: float) -> Tuple[float, float]:
            ix = ox + (x - minx) * img_scale
            iy = oy + (maxy - y) * img_scale
            return ix, iy

        svg_content = f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">\n<rect width="100%" height="100%" fill="#101015" />\n'
        # Polygons
        for p in self.board.polygons:
            if p.layer not in visible_layers:
                continue
            color = self._layer_color(p.layer)
            fill = self._lighten_color(color) if p.fill else 'none'
            points_str = ' '.join(f'{world_to_img(vx, vy)[0]},{world_to_img(vx, vy)[1]}' for vx, vy in p.vertices)
            line_width = max(1.0, p.width * img_scale)
            svg_content += f'<polygon points="{points_str}" fill="{fill}" stroke="{color}" stroke-width="{line_width}" />\n'

        # Wires
        for w in self.board.wires:
            if w.layer not in visible_layers:
                continue
            color = self._layer_color(w.layer)
            ix1, iy1 = world_to_img(w.x1, w.y1)
            ix2, iy2 = world_to_img(w.x2, w.y2)
            line_width = max(1.0, w.width * img_scale)
            svg_content += f'<line x1="{ix1}" y1="{iy1}" x2="{ix2}" y2="{iy2}" stroke="{color}" stroke-width="{line_width}" />\n'

        # Pads
        for p in self.board.pads:
            if p.layer not in visible_layers:
                continue
            color = self._layer_color(p.layer)
            ix, iy = world_to_img(p.x, p.y)
            angle = math.radians(p.rot)
            if p.shape != 'round' and p.dx > 0 and p.dy > 0:
                hw = p.dx * img_scale / 2
                hh = p.dy * img_scale / 2
                points = [
                    (hw * math.cos(angle) - hh * math.sin(angle), hw * math.sin(angle) + hh * math.cos(angle)),
                    (hw * math.cos(angle) + hh * math.sin(angle), hw * math.sin(angle) - hh * math.cos(angle)),
                    (-hw * math.cos(angle) + hh * math.sin(angle), -hw * math.sin(angle) - hh * math.cos(angle)),
                    (-hw * math.cos(angle) - hh * math.sin(angle), -hw * math.sin(angle) + hh * math.cos(angle)),
                ]
                points_str = ' '.join(f'{ix + px},{iy + py}' for px, py in points)
                svg_content += f'<polygon points="{points_str}" stroke="{color}" stroke-width="1" fill="none" />\n'
            else:
                r = max(p.diameter, 0.1) * img_scale / 2
                svg_content += f'<circle cx="{ix}" cy="{iy}" r="{r}" stroke="{color}" stroke-width="1" fill="none" />\n'
            if p.drill > 0:
                dr = p.drill * img_scale / 2
                svg_content += f'<circle cx="{ix}" cy="{iy}" r="{dr}" fill="white" />\n'

        # SMDs
        for s in self.board.smds:
            if s.layer not in visible_layers:
                continue
            color = self._layer_color(s.layer)
            ix, iy = world_to_img(s.x, s.y)
            angle = math.radians(s.rot)
            hw = s.dx * img_scale / 2
            hh = s.dy * img_scale / 2
            points = [
                (hw * math.cos(angle) - hh * math.sin(angle), hw * math.sin(angle) + hh * math.cos(angle)),
                (hw * math.cos(angle) + hh * math.sin(angle), hw * math.sin(angle) - hh * math.cos(angle)),
                (-hw * math.cos(angle) + hh * math.sin(angle), -hw * math.sin(angle) - hh * math.cos(angle)),
                (-hw * math.cos(angle) - hh * math.sin(angle), -hw * math.sin(angle) + hh * math.cos(angle)),
            ]
            points_str = ' '.join(f'{ix + px},{iy + py}' for px, py in points)
            svg_content += f'<polygon points="{points_str}" stroke="{color}" stroke-width="1" fill="{color}" />\n'

        # Vias
        for v in self.board.vias:
            ix, iy = world_to_img(v.x, v.y)
            r = max(v.diameter or 0, v.drill or 0.1) * img_scale / 2
            svg_content += f'<circle cx="{ix}" cy="{iy}" r="{r}" stroke="white" stroke-width="1" fill="none" />\n'
            if v.drill > 0:
                dr = v.drill * img_scale / 2
                svg_content += f'<circle cx="{ix}" cy="{iy}" r="{dr}" fill="white" />\n'

        # Texts
        for t in self.board.texts:
            if t.layer not in visible_layers:
                continue
            color = self._layer_color(t.layer)
            ix, iy = world_to_img(t.x, t.y)
            font_size = int(t.size * img_scale)
            svg_content += f'<text x="{ix}" y="{iy}" fill="{color}" font-family="Segoe UI" font-size="{font_size}" transform="rotate({t.rot} {ix},{iy})">{t.text}</text>\n'

        # Elements
        for e in self.board.elements:
            ix, iy = world_to_img(e.x, e.y)
            size = 6
            svg_content += f'<line x1="{ix - size}" y1="{iy}" x2="{ix + size}" y2="{iy}" stroke="gray" stroke-width="1" />\n'
            svg_content += f'<line x1="{ix}" y1="{iy - size}" x2="{ix}" y2="{iy + size}" stroke="gray" stroke-width="1" />\n'
            svg_content += f'<text x="{ix + 8}" y="{iy - 8}" fill="white" font-family="Segoe UI" font-size="9" font-weight="bold">{e.name}</text>\n'

        svg_content += '</svg>'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        self.status_lbl.config(text=f"Exported SVG: {os.path.basename(path)}")

    def _color_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i + 2], 16) for i in range(0, 6, 2))

    def _lighten_color(self, hex_color, factor=0.5):
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        white = (255, 255, 255)
        new_rgb = tuple(int(rgb[i] + (white[i] - rgb[i]) * factor) for i in range(3))
        return f'#{new_rgb[0]:02x}{new_rgb[1]:02x}{new_rgb[2]:02x}'

    def save_project(self):
        if not self.board:
            messagebox.showinfo("Save Project", "Open a .brd first.")
            return
        data = {
            'file': os.path.abspath(self.file_path or ''),
            'scale': self.scale,
            'offset_x': self.offset_x,
            'offset_y': self.offset_y,
            'layer_visibility': {str(k): v.get() for k, v in self.layer_checks.items()},
            'search': self.search_var.get(),
            'net_search': self.net_search_var.get(),
        }
        path = filedialog.asksaveasfilename(title='Save Project', defaultextension='.pvproj', filetypes=[('PCB Viewer Project', '*.pvproj')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.status_lbl.config(text=f"Saved project: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def load_project(self):
        path = filedialog.askopenfilename(title='Load Project', filetypes=[('PCB Viewer Project', '*.pvproj'), ('All Files', '*.*')])
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return
        # Load file if different
        brd_path = data.get('file', '')
        if brd_path and (not self.file_path or os.path.abspath(self.file_path) != os.path.abspath(brd_path)):
            try:
                if brd_path.lower().endswith('.kicad_pcb'):
                    parser = KicadParser(brd_path)
                else:
                    parser = EagleParser(brd_path)
                board = parser.parse()
                self.board = board
                self.file_path = brd_path
                self._populate_layers()
                self._populate_components()
                self._populate_nets()
            except Exception as e:
                messagebox.showerror("Open failed", f"While opening {brd_path}: {e}")
                return
        # Apply view
        self.scale = float(data.get('scale', self.scale))
        self.offset_x = float(data.get('offset_x', self.offset_x))
        self.offset_y = float(data.get('offset_y', self.offset_y))
        vis = data.get('layer_visibility', {})
        for k, var in self.layer_checks.items():
            if str(k) in vis:
                var.set(bool(vis[str(k)]))
        self.search_var.set(data.get('search', ''))
        self._on_search()
        self.net_search_var.set(data.get('net_search', ''))
        self._on_net_search()
        self.redraw()
        self.status_lbl.config(text=f"Loaded project: {os.path.basename(path)}")

    # ----- Sidebars -----
    def _populate_layers(self):
        for w in self.layer_inner.winfo_children():
            w.destroy()
        self.layer_checks.clear()
        if not self.board:
            return
        layers_sorted = sorted(self.board.layers.values(), key=lambda L: L.number)
        for L in layers_sorted:
            var = tk.BooleanVar(value=L.visible)
            cb = ttk.Checkbutton(self.layer_inner, text=f"{L.number:>2}  {L.name}", variable=var, command=self.redraw)
            cb.pack(anchor='w', padx=8, pady=2)
            self.layer_checks[L.number] = var
        self.layer_canvas.update_idletasks()

    def _populate_components(self):
        self.comp_list.delete(0, tk.END)
        if not self.board:
            return
        for e in self.board.elements:
            label = f"{e.name}  ({e.value})  @{e.x:.3f},{e.y:.3f}"
            self.comp_list.insert(tk.END, label)

    def _on_search(self, event=None):
        if not self.board:
            return
        q = self.search_var.get().strip().lower()
        self.comp_list.delete(0, tk.END)
        for e in self.board.elements:
            label = f"{e.name}  ({e.value})  @{e.x:.3f},{e.y:.3f}"
            if not q or q in e.name.lower() or q in e.value.lower() or q in e.package.lower():
                self.comp_list.insert(tk.END, label)

    def _on_component_select(self, event=None):
        if not self.board:
            return
        sel = self.comp_list.curselection()
        if not sel:
            return
        idx = sel[0]
        q = self.search_var.get().strip().lower()
        filtered = [e for e in self.board.elements if (not q or q in e.name.lower() or q in e.value.lower() or q in e.package.lower())]
        if 0 <= idx < len(filtered):
            self.selected_element = filtered[idx]
            self.selected_net = None
            self._zoom_to_point(self.selected_element.x, self.selected_element.y)
            self.redraw()

    def _populate_nets(self):
        self.net_list.delete(0, tk.END)
        if not self.board:
            return
        nets = set()
        for w in self.board.wires:
            if w.net:
                nets.add(w.net)
        for v in self.board.vias:
            if v.net:
                nets.add(v.net)
        for poly in self.board.polygons:
            if poly.net:
                nets.add(poly.net)
        for net in sorted(nets):
            self.net_list.insert(tk.END, net)

    def _on_net_search(self, event=None):
        if not self.board:
            return
        q = self.net_search_var.get().strip().lower()
        self.net_list.delete(0, tk.END)
        nets = set()
        for w in self.board.wires:
            if w.net:
                nets.add(w.net)
        for v in self.board.vias:
            if v.net:
                nets.add(v.net)
        for poly in self.board.polygons:
            if poly.net:
                nets.add(poly.net)
        for net in sorted(nets):
            if not q or q in net.lower():
                self.net_list.insert(tk.END, net)

    def _on_net_select(self, event=None):
        if not self.board:
            return
        sel = self.net_list.curselection()
        if not sel:
            return
        idx = sel[0]
        q = self.net_search_var.get().strip().lower()
        nets = set()
        for w in self.board.wires:
            if w.net:
                nets.add(w.net)
        for v in self.board.vias:
            if v.net:
                nets.add(v.net)
        for poly in self.board.polygons:
            if poly.net:
                nets.add(poly.net)
        filtered = [n for n in sorted(nets) if not q or q in n.lower()]
        if 0 <= idx < len(filtered):
            self.selected_net = filtered[idx]
            self.selected_element = None
            self.redraw()

    def world_to_screen(self, x: float, y: float) -> Tuple[float, float]:
        sx = self.offset_x + x * self.scale
        sy = self.offset_y + (-y) * self.scale
        return sx, sy

    def screen_to_world(self, sx: float, sy: float) -> Tuple[float, float]:
        x = (sx - self.offset_x) / self.scale
        y = - (sy - self.offset_y) / self.scale
        return x, y

    def fit_to_view(self):
        if not self.board or not self.board.bounds:
            return
        minx, miny, maxx, maxy = self.board.bounds
        w = maxx - minx
        h = maxy - miny
        if w <= 0 or h <= 0:
            return
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)
        pad = 40
        sx = (cw - 2*pad) / w
        sy = (ch - 2*pad) / h
        self.scale = max(0.1, min(sx, sy))
        cx_world = (minx + maxx) / 2
        cy_world = (miny + maxy) / 2
        cx_screen = cw / 2
        cy_screen = ch / 2
        self.offset_x = cx_screen - cx_world * self.scale
        self.offset_y = cy_screen - (-cy_world) * self.scale
        self._update_zoom_label()
        self.redraw()

    def reset_view(self):
        self.scale = 5.0
        self.offset_x = 100.0
        self.offset_y = 100.0
        self._update_zoom_label()
        self.redraw()

    def _zoom_to_point(self, x: float, y: float, target_pixels: float = 40.0):
        self.scale = max(0.1, min(self.scale, 1000.0))
        if self.scale < target_pixels:
            self.scale = target_pixels
        cw = max(self.canvas.winfo_width(), 100)
        ch = max(self.canvas.winfo_height(), 100)
        self.offset_x = cw/2 - x * self.scale
        self.offset_y = ch/2 - (-y) * self.scale
        self._update_zoom_label()
        self.redraw()

    def _update_zoom_label(self):
        self.zoom_lbl.config(text=f"Zoom: {int(self.scale*100)}%")

    def clear_measure(self):
        self.measure_points = []
        self.redraw()

    def redraw(self):
        self.canvas.delete('all')
        if not self.board:
            return
        self._draw_grid()
        visible_layers = {num for num, var in self.layer_checks.items() if var.get()}
        for p in self.board.polygons:
            if p.layer in visible_layers:
                self._draw_polygon(p)
        for w in self.board.wires:
            if w.layer in visible_layers:
                self._draw_wire(w)
        for p in self.board.pads:
            if p.layer in visible_layers:
                self._draw_pad(p)
        for s in self.board.smds:
            if s.layer in visible_layers:
                self._draw_smd(s)
        for v in self.board.vias:
            self._draw_via(v)
        for t in self.board.texts:
            if t.layer in visible_layers:
                self._draw_text(t)
        for e in self.board.elements:
            self._draw_element_marker(e)
            self._draw_element_shapes(e, visible_layers, highlight=(e == self.selected_element))

        if self.selected_net:
            for p in self.board.polygons:
                if p.net == self.selected_net and p.layer in visible_layers:
                    self._draw_polygon(p, highlight=True)
            for w in self.board.wires:
                if w.net == self.selected_net and w.layer in visible_layers:
                    self._draw_wire(w, highlight=True)
            for v in self.board.vias:
                if v.net == self.selected_net:
                    self._draw_via(v, highlight=True)

        if self.selected_element:
            sx, sy = self.world_to_screen(self.selected_element.x, self.selected_element.y)
            r = 20
            self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, outline="#FFFF00", width=2)

        if len(self.measure_points) == 1:
            sx, sy = self.world_to_screen(*self.measure_points[0])
            self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, outline="#66FF66")
        elif len(self.measure_points) >= 2:
            p1, p2 = self.measure_points[-2], self.measure_points[-1]
            sx1, sy1 = self.world_to_screen(*p1)
            sx2, sy2 = self.world_to_screen(*p2)
            self.canvas.create_line(sx1, sy1, sx2, sy2, fill="#66FF66", width=2)
            d = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
            midx, midy = (sx1+sx2)/2, (sy1+sy2)/2
            self.canvas.create_text(midx+8, midy-8, text=f"{d:.3f} units", fill="#A0FFA0", anchor='w', font=("Segoe UI", 9, "bold"))

    def _draw_grid(self):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 0 or ch <= 0:
            return
        step_world = max(1.0, 50.0 / max(self.scale, 0.0001))
        start_x_world, start_y_world = self.screen_to_world(0, 0)
        end_x_world, end_y_world = self.screen_to_world(cw, ch)
        gx = math.floor(start_x_world/step_world)*step_world
        while gx < end_x_world:
            sx, _ = self.world_to_screen(gx, 0)
            self.canvas.create_line(sx, 0, sx, ch, fill="#151525")
            gx += step_world
        gy = math.floor(start_y_world/step_world)*step_world
        while gy < end_y_world:
            _, sy = self.world_to_screen(0, gy)
            self.canvas.create_line(0, sy, cw, sy, fill="#151525")
            gy += step_world

    def _get_eagle_palette_color(self, index: int) -> str:
        palette = {
            1: "#0000FF",
            2: "#00FF00",
            3: "#00FFFF",
            4: "#FF0000",
            5: "#FF00FF",
            6: "#FFFF00",
            7: "#FFFFFF",
            8: "#808080",
            9: "#800000",
            10: "#808000",
            11: "#800080",
            12: "#000080",
            13: "#008000",
            14: "#008080",
            15: "#8080FF",
        }
        return palette.get(index, "#FFFFFF")

    def _get_kicad_layer_color(self, num: int) -> str:
        map_ = {
            1: "#C33427",  # F.Cu
            16: "#37965C",  # B.Cu
            21: "#CCC3B7",  # F.SilkS
            22: "#CCC3B7",  # B.SilkS
            29: "#A013A0",  # F.Mask
            30: "#A013A0",  # B.Mask
            20: "#FFFF00",  # Edge.Cuts
            43: "#808080",  # Dwgs.User
        }
        return map_.get(num, "#00FFD1")

    def _layer_color(self, layer_num: int) -> str:
        if self.file_path and self.file_path.lower().endswith('.brd'):
            color_index = self.board.layers.get(layer_num, Layer(0, "", 7)).color
            return self._get_eagle_palette_color(color_index)
        else:
            return self._get_kicad_layer_color(layer_num)

    def _draw_wire(self, w: Wire, highlight: bool = False):
        sx1, sy1 = self.world_to_screen(w.x1, w.y1)
        sx2, sy2 = self.world_to_screen(w.x2, w.y2)
        color = "#FFFF00" if highlight else self._layer_color(w.layer)
        width = max(1, int(w.width * self.scale)) + (2 if highlight else 0)
        self.canvas.create_line(sx1, sy1, sx2, sy2, fill=color, width=width)

    def _draw_pad(self, p: Pad, highlight: bool = False):
        sx, sy = self.world_to_screen(p.x, p.y)
        color = "#FFFF00" if highlight else self._layer_color(p.layer)
        angle = math.radians(p.rot)
        if p.shape != 'round' and p.dx > 0 and p.dy > 0:
            hw = p.dx * self.scale / 2
            hh = p.dy * self.scale / 2
            points = [
                (hw * math.cos(angle) - hh * math.sin(angle), hw * math.sin(angle) + hh * math.cos(angle)),
                (hw * math.cos(angle) + hh * math.sin(angle), hw * math.sin(angle) - hh * math.cos(angle)),
                (-hw * math.cos(angle) + hh * math.sin(angle), -hw * math.sin(angle) - hh * math.cos(angle)),
                (-hw * math.cos(angle) - hh * math.sin(angle), -hw * math.sin(angle) + hh * math.cos(angle)),
            ]
            screen_points = []
            for px, py in points:
                screen_points.append(sx + px)
                screen_points.append(sy + py)
            self.canvas.create_polygon(screen_points, outline=color, width=1, fill='')
        else:
            r = max(p.diameter, 0.1) * self.scale / 2
            self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, outline=color, width=1, fill='')
        if p.drill > 0:
            dr = max(1, int(p.drill * self.scale / 2))
            self.canvas.create_oval(sx - dr, sy - dr, sx + dr, sy + dr, fill='white', outline='')

    def _draw_smd(self, s: SMD, highlight: bool = False):
        sx, sy = self.world_to_screen(s.x, s.y)
        color = "#FFFF00" if highlight else self._layer_color(s.layer)
        angle = math.radians(s.rot)
        hw = max(1, int(s.dx * self.scale / 2))
        hh = max(1, int(s.dy * self.scale / 2))
        points = [
            (hw * math.cos(angle) - hh * math.sin(angle), hw * math.sin(angle) + hh * math.cos(angle)),
            (hw * math.cos(angle) + hh * math.sin(angle), hw * math.sin(angle) - hh * math.cos(angle)),
            (-hw * math.cos(angle) + hh * math.sin(angle), -hw * math.sin(angle) - hh * math.cos(angle)),
            (-hw * math.cos(angle) - hh * math.sin(angle), -hw * math.sin(angle) + hh * math.cos(angle)),
        ]
        screen_points = []
        for px, py in points:
            screen_points.append(sx + px)
            screen_points.append(sy + py)
        self.canvas.create_polygon(screen_points, outline=color, width=1, fill=color)

    def _draw_via(self, v: Via, highlight: bool = False):
        sx, sy = self.world_to_screen(v.x, v.y)
        color = "#FFFF00" if highlight else "#FFFFFF"
        r = max(2, int(max(v.diameter, v.drill) * self.scale / 2)) if (v.diameter or v.drill) else 3
        width = 2 if highlight else 1
        self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, outline=color, width=width)
        self.canvas.create_oval(sx - 1, sy - 1, sx + 1, sy + 1, fill="#FFFFFF", outline="")

    def _draw_polygon(self, p: Polygon, highlight: bool = False):
        points = []
        for vx, vy in p.vertices:
            sx, sy = self.world_to_screen(vx, vy)
            points.append(sx)
            points.append(sy)
        color = "#FFFF00" if p.is_outline or highlight else self._layer_color(p.layer)
        width = max(2 if p.is_outline else 1, int(p.width * self.scale)) + (2 if highlight else 0)
        fill = self._lighten_color(color) if p.fill else ''
        self.canvas.create_polygon(points, outline=color, width=width, fill=fill)

    def _draw_text(self, t: Text):
        sx, sy = self.world_to_screen(t.x, t.y)
        color = self._layer_color(t.layer)
        font_size = max(1, int(t.size * self.scale))
        self.canvas.create_text(sx, sy, text=t.text, fill=color, anchor='center', font=("Segoe UI", font_size))

    def _draw_element_marker(self, e: Element):
        sx, sy = self.world_to_screen(e.x, e.y)
        size = 6
        self.canvas.create_line(sx - size, sy, sx + size, sy, fill="#DDDDDD")
        self.canvas.create_line(sx, sy - size, sx, sy + size, fill="#DDDDDD")
        self.canvas.create_text(sx + 8, sy - 8, text=e.name, fill="#FFFFFF", anchor='w', font=("Segoe UI", 9, "bold"))

    def _draw_circle(self, c: Circle, highlight: bool = False):
        sx, sy = self.world_to_screen(c.x, c.y)
        color = "#FFFF00" if highlight else self._layer_color(c.layer)
        r = c.radius * self.scale
        width = max(1, int(c.width * self.scale)) + (2 if highlight else 0)
        self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, outline=color, width=width)

    def _draw_rect(self, r: Rect, highlight: bool = False):
        color = "#FFFF00" if highlight else self._layer_color(r.layer)
        angle = math.radians(r.rot)
        x_min = min(r.x1, r.x2)
        x_max = max(r.x1, r.x2)
        y_min = min(r.y1, r.y2)
        y_max = max(r.y1, r.y2)
        cx = (x_min + x_max) / 2
        cy = (y_min + y_max) / 2
        hw = (x_max - x_min) / 2 * self.scale
        hh = (y_max - y_min) / 2 * self.scale
        points = [
            (hw * math.cos(angle) - hh * math.sin(angle), hw * math.sin(angle) + hh * math.cos(angle)),
            (hw * math.cos(angle) + hh * math.sin(angle), hw * math.sin(angle) - hh * math.cos(angle)),
            (-hw * math.cos(angle) + hh * math.sin(angle), -hw * math.sin(angle) - hh * math.cos(angle)),
            (-hw * math.cos(angle) - hh * math.sin(angle), -hw * math.sin(angle) + hh * math.cos(angle)),
        ]
        sx, sy = self.world_to_screen(cx, cy)
        screen_points = []
        for px, py in points:
            screen_points.append(sx + px)
            screen_points.append(sy + py)
        self.canvas.create_polygon(screen_points, fill=color, outline='', width=0)

    def _draw_element_shapes(self, e: Element, visible_layers, highlight: bool = False):
        package_shapes = self.board.packages.get(e.package, [])
        angle = math.radians(self._parse_rot(e.rot))
        mirror = 'M' in e.rot
        for shape in package_shapes:
            if isinstance(shape, Wire):
                rx1 = shape.x1 if not mirror else -shape.x1
                ry1 = shape.y1
                rx1_rot = rx1 * math.cos(angle) - ry1 * math.sin(angle)
                ry1_rot = rx1 * math.sin(angle) + ry1 * math.cos(angle)
                abs_x1 = e.x + rx1_rot
                abs_y1 = e.y + ry1_rot

                rx2 = shape.x2 if not mirror else -shape.x2
                ry2 = shape.y2
                rx2_rot = rx2 * math.cos(angle) - ry2 * math.sin(angle)
                ry2_rot = rx2 * math.sin(angle) + ry2 * math.cos(angle)
                abs_x2 = e.x + rx2_rot
                abs_y2 = e.y + ry2_rot

                w_transformed = Wire(x1=abs_x1, y1=abs_y1, x2=abs_x2, y2=abs_y2, width=shape.width, layer=self._flip_layer(shape.layer) if mirror else shape.layer)
                if w_transformed.layer in visible_layers:
                    self._draw_wire(w_transformed, highlight=highlight)
            elif isinstance(shape, Circle):
                rx = shape.x if not mirror else -shape.x
                ry = shape.y
                rx_rot = rx * math.cos(angle) - ry * math.sin(angle)
                ry_rot = rx * math.sin(angle) + ry * math.cos(angle)
                abs_x = e.x + rx_rot
                abs_y = e.y + ry_rot
                shape_layer = self._flip_layer(shape.layer) if mirror else shape.layer
                if shape_layer in visible_layers:
                    self._draw_circle(Circle(abs_x, abs_y, shape.radius, shape.width, shape_layer), highlight=highlight)
            elif isinstance(shape, Rect):
                x1 = shape.x1 if not mirror else -shape.x1
                y1 = shape.y1
                x2 = shape.x2 if not mirror else -shape.x2
                y2 = shape.y2
                x_min = min(x1, x2)
                x_max = max(x1, x2)
                y_min = min(y1, y2)
                y_max = max(y1, y2)
                cx = (x_min + x_max) / 2
                cy = (y_min + y_max) / 2
                cx_rot = cx * math.cos(angle) - cy * math.sin(angle)
                cy_rot = cx * math.sin(angle) + cy * math.cos(angle)
                abs_cx = e.x + cx_rot
                abs_cy = e.y + cy_rot
                shape_rot = shape.rot + (self._parse_rot(e.rot) if not mirror else -self._parse_rot(e.rot))
                shape_layer = self._flip_layer(shape.layer) if mirror else shape.layer
                if shape_layer in visible_layers:
                    points_rel = [
                        (x_min - cx, y_min - cy),
                        (x_min - cx, y_max - cy),
                        (x_max - cx, y_min - cy),
                        (x_max - cx, y_max - cy),
                    ]
                    points_rot = []
                    for px, py in points_rel:
                        pxr = px * math.cos(angle) - py * math.sin(angle)
                        pyr = px * math.sin(angle) + py * math.cos(angle)
                        abs_x = e.x + pxr
                        abs_y = e.y + pyr
                        points_rot.append((abs_x, abs_y))
                    screen_points = []
                    for abs_x, abs_y in points_rot:
                        sx, sy = self.world_to_screen(abs_x, abs_y)
                        screen_points.append(sx)
                        screen_points.append(sy)
                    color = "#FFFF00" if highlight else self._layer_color(shape_layer)
                    self.canvas.create_polygon(screen_points, fill=color, outline='', width=0)
            elif isinstance(shape, Polygon):
                verts_transformed = []
                for vx, vy in shape.vertices:
                    rx = vx if not mirror else -vx
                    ry = vy
                    rx_rot = rx * math.cos(angle) - ry * math.sin(angle)
                    ry_rot = rx * math.sin(angle) + ry * math.cos(angle)
                    abs_x = e.x + rx_rot
                    abs_y = e.y + ry_rot
                    verts_transformed.append((abs_x, abs_y))
                shape_layer = self._flip_layer(shape.layer) if mirror else shape.layer
                if shape_layer in visible_layers:
                    p_transformed = Polygon(vertices=verts_transformed, layer=shape_layer, width=shape.width, net=shape.net, fill=shape.fill, is_outline=shape.is_outline)
                    self._draw_polygon(p_transformed, highlight=highlight)
            else:
                rx = shape.x if not mirror else -shape.x
                ry = shape.y
                rx_rot = rx * math.cos(angle) - ry * math.sin(angle)
                ry_rot = rx * math.sin(angle) + ry * math.cos(angle)
                abs_x = e.x + rx_rot
                abs_y = e.y + ry_rot
                shape_rot = shape.rot + (self._parse_rot(e.rot) if not mirror else -self._parse_rot(e.rot))
                shape_layer = self._flip_layer(shape.layer) if mirror else shape.layer
                if shape_layer not in visible_layers:
                    continue
                if isinstance(shape, Pad):
                    p_transformed = Pad(name=shape.name, x=abs_x, y=abs_y, drill=shape.drill, diameter=shape.diameter, dx=shape.dx, dy=shape.dy, shape=shape.shape, layer=shape_layer, rot=shape_rot)
                    self._draw_pad(p_transformed, highlight=highlight)
                elif isinstance(shape, SMD):
                    s_transformed = SMD(name=shape.name, x=abs_x, y=abs_y, dx=shape.dx, dy=shape.dy, layer=shape_layer, roundness=shape.roundness, rot=shape_rot)
                    self._draw_smd(s_transformed, highlight=highlight)

    def _parse_rot(self, rot_str: str) -> float:
        if not rot_str:
            return 0.0
        mirror = rot_str[0] == 'M'
        rot_str = rot_str.lstrip('M')
        rot = float(rot_str.lstrip('R')) if rot_str else 0.0
        if mirror:
            rot = -rot
        return rot

    def _flip_layer(self, layer: int) -> int:
        flip_map = {
            1: 16, 16: 1,
            21: 22, 22: 21,
            25: 26, 26: 25,
            29: 30, 30: 29,
        }
        return flip_map.get(layer, layer)

    def _on_mouse_move(self, event):
        xw, yw = self.screen_to_world(event.x, event.y)
        self.status_lbl.config(text=f"x={xw:.3f}, y={yw:.3f}")

    def _on_left_down(self, event):
        if self.measure_mode.get():
            xw, yw = self.screen_to_world(event.x, event.y)
            self.measure_points.append((xw, yw))
            if len(self.measure_points) > 2:
                self.measure_points = self.measure_points[-2:]
            self.redraw()
        else:
            self._drag_start = (event.x, event.y, self.offset_x, self.offset_y)

    def _on_left_drag(self, event):
        if self._drag_start is None:
            return
        sx0, sy0, ox0, oy0 = self._drag_start
        dx = event.x - sx0
        dy = event.y - sy0
        self.offset_x = ox0 + dx
        self.offset_y = oy0 + dy
        self.redraw()

    def _on_mid_down(self, event):
        self._drag_start = (event.x, event.y, self.offset_x, self.offset_y)

    def _on_mid_drag(self, event):
        if self._drag_start is None:
            return
        sx0, sy0, ox0, oy0 = self._drag_start
        dx = event.x - sx0
        dy = event.y - sy0
        self.offset_x = ox0 + dx
        self.offset_y = oy0 + dy
        self.redraw()

    def _on_mouse_wheel(self, event):
        if hasattr(event, 'delta') and event.delta:
            delta = event.delta
        else:
            delta = 120 if getattr(event, 'num', 0) == 4 else -120
        factor = 1.0 + (0.1 if delta > 0 else -0.1)
        xw_before, yw_before = self.screen_to_world(event.x, event.y)
        self.scale = max(0.05, min(self.scale * factor, 200.0))
        xw_after, yw_after = self.screen_to_world(event.x, event.y)
        self.offset_x += (xw_after - xw_before) * self.scale
        self.offset_y += (-yw_after + yw_before) * self.scale
        self._update_zoom_label()
        self.redraw()

# ------------------------------
# Main
# ------------------------------
if __name__ == '__main__':
    app = BRDViewer()
    app.mainloop()