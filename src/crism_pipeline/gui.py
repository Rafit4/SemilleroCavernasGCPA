"""Interfaz gráfica CRISM Pipeline — GCPA.

Stack: CustomTkinter (moderno, nativo). El CLI no se modifica.
Lanzar:  crism-pipeline-gui  |  python -m crism_pipeline.gui
"""

from __future__ import annotations

import html
import queue
import re
import tempfile
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk
from PIL import Image

from .config import ROOT, resolve_path, viviano_config

DEFAULT_BROWSE = ["MAF", "PHY", "HYD", "CAR", "FEM"]

# Paleta científica (navy + cian hielo; sin púrpura genérico)
COLORS = {
    "bg": "#0b1220",
    "panel": "#141e2e",
    "card": "#1a2740",
    "border": "#2a3b55",
    "accent": "#4ec4e0",
    "accent_dim": "#2a7a8c",
    "text": "#e8eef7",
    "muted": "#8fa3bf",
    "ok": "#3ecf8e",
    "err": "#e86a6a",
    "warn": "#e0b35a",
}

DOCS = [
    ("Manual de la interfaz", "08_manual_gui.md"),
    ("Conceptos CRISM / SR", "01_conceptos.md"),
    ("Instalación", "02_instalacion.md"),
    ("Descarga ODE", "03_descarga.md"),
    ("Pipeline de procesamiento", "04_pipeline_procesamiento.md"),
    ("Mapas minerales", "05_mapas_minerales.md"),
    ("Detección de minerales", "06_deteccion_minerales.md"),
    ("Clasificación de unidades", "07_clasificacion_unidades.md"),
]

_TAB_NAMES = (
    "Descarga",
    "Exportar",
    "Mapas",
    "Detección",
    "Clasificación",
    "Espectros IF",
    "Pipeline",
    "Ayuda",
)


def _logo_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "gcpa_logo.png"


def _docs_dir() -> Path:
    return ROOT / "docs"


def _q(value: str) -> str:
    return f'"{value}"'


def _input_arg(value: str) -> str:
    return _q(value.strip() or "<path>")


def _tk_text_target(widget):
    """Widget tk interno de CTkEntry / CTkTextbox (o el propio widget)."""
    if hasattr(widget, "_entry"):
        return widget._entry
    if hasattr(widget, "_textbox"):
        return widget._textbox
    return widget


def enable_edit_context_menu(widget, *, readonly: bool = False) -> None:
    """Menú clic derecho: Cortar / Copiar / Pegar / Seleccionar todo (+ atajos)."""
    import tkinter as tk

    target = _tk_text_target(widget)
    menu = tk.Menu(
        widget,
        tearoff=0,
        bg=COLORS["card"],
        fg=COLORS["text"],
        activebackground=COLORS["accent_dim"],
        activeforeground=COLORS["text"],
        bd=0,
    )

    def _is_text() -> bool:
        return target.winfo_class() in {"Text", "CTkTextbox"} or hasattr(widget, "_textbox")

    def do_cut() -> None:
        if readonly:
            return
        try:
            target.event_generate("<<Cut>>")
        except tk.TclError:
            pass

    def do_copy() -> None:
        try:
            was_disabled = False
            try:
                was_disabled = str(widget.cget("state")) == "disabled"
            except tk.TclError:
                pass
            if was_disabled:
                widget.configure(state="normal")
            target.event_generate("<<Copy>>")
            if was_disabled:
                widget.configure(state="disabled")
        except tk.TclError:
            pass

    def do_paste() -> None:
        if readonly:
            return
        try:
            target.event_generate("<<Paste>>")
        except tk.TclError:
            pass

    def do_select_all() -> None:
        try:
            was_disabled = False
            try:
                was_disabled = str(widget.cget("state")) == "disabled"
            except tk.TclError:
                pass
            if was_disabled:
                widget.configure(state="normal")
            if _is_text():
                target.tag_add("sel", "1.0", "end-1c")
                target.mark_set("insert", "1.0")
                target.see("insert")
            else:
                target.select_range(0, "end")
                target.icursor("end")
            if was_disabled:
                widget.configure(state="disabled")
        except tk.TclError:
            pass

    if not readonly:
        menu.add_command(label="Cortar\tCtrl+X", command=do_cut)
    menu.add_command(label="Copiar\tCtrl+C", command=do_copy)
    if not readonly:
        menu.add_command(label="Pegar\tCtrl+V", command=do_paste)
    menu.add_separator()
    menu.add_command(label="Seleccionar todo\tCtrl+A", command=do_select_all)

    def popup(event) -> str | None:
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    for w in {widget, target}:
        w.bind("<Button-3>", popup, add="+")
        # Atajos explícitos (CustomTkinter a veces no los propaga igual)
        if not readonly:
            w.bind("<Control-x>", lambda e: (do_cut(), "break")[1], add="+")
            w.bind("<Control-v>", lambda e: (do_paste(), "break")[1], add="+")
            w.bind("<Control-X>", lambda e: (do_cut(), "break")[1], add="+")
            w.bind("<Control-V>", lambda e: (do_paste(), "break")[1], add="+")
        w.bind("<Control-c>", lambda e: (do_copy(), "break")[1], add="+")
        w.bind("<Control-C>", lambda e: (do_copy(), "break")[1], add="+")
        w.bind("<Control-a>", lambda e: (do_select_all(), "break")[1], add="+")
        w.bind("<Control-A>", lambda e: (do_select_all(), "break")[1], add="+")


def make_entry(master, *, readonly: bool = False, **kwargs):
    """CTkEntry con menú contextual de edición."""
    if readonly:
        kwargs.setdefault("state", "readonly")
    entry = ctk.CTkEntry(master, **kwargs)
    enable_edit_context_menu(entry, readonly=readonly or kwargs.get("state") == "readonly")
    return entry


def _mineral_keys() -> list[str]:
    return list(viviano_config().get("mineral_detection", {}).keys())


def _browse_codes() -> list[str]:
    return list(viviano_config().get("browse_products", {}).keys())


def _list_raw_products() -> list[Path]:
    raw = resolve_path("raw")
    if not raw.is_dir():
        return []
    return sorted(p for p in raw.iterdir() if p.is_dir())


def _open_path(path: Path) -> bool:
    """Abre un archivo/carpeta con el visor del sistema. Devuelve True si ok."""
    import os
    import subprocess
    import sys

    path = path.resolve()
    if not path.exists():
        messagebox.showerror("No encontrado", str(path))
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except OSError as exc:
        messagebox.showerror("No se pudo abrir", f"{path}\n\n{exc}")
        return False


def _rewrite_md_hrefs(fragment: str) -> str:
    """Convierte enlaces relativos *.md → *.html para el sitio de docs generado."""

    def repl(match: re.Match[str]) -> str:
        href = match.group(1).strip()
        if re.match(r"^(https?:|mailto:|file:|#)", href, re.I):
            return match.group(0)
        path_part, frag = href, ""
        if "#" in href:
            path_part, frag = href.split("#", 1)
            frag = "#" + frag
        name = Path(path_part).name
        if not name:
            return match.group(0)
        if name.lower().endswith(".md"):
            name = f"{name[:-3]}.html"
        return f'href="{html.escape(name + frag)}"'

    return re.sub(r'href="([^"]+)"', repl, fragment)


_DOC_PAGE_CSS = """
  body { font-family: Segoe UI, system-ui, sans-serif; max-width: 900px;
         margin: 1.5rem auto; padding: 0 1.2rem 2rem; line-height: 1.55;
         background: #0b1220; color: #e8eef7; }
  h1,h2,h3,h4 { color: #4ec4e0; }
  a { color: #7dd3fc; }
  a:visited { color: #a5d8ff; }
  code, pre { background: #1a2740; border-radius: 6px; }
  code { padding: 0.1em 0.35em; font-size: 0.92em; }
  pre { padding: 1rem; overflow-x: auto; }
  pre code { padding: 0; background: transparent; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #2a3b55; padding: 0.45rem 0.65rem; text-align: left; }
  th { background: #1a2740; }
  ul, ol { padding-left: 1.4rem; }
  blockquote { border-left: 3px solid #4ec4e0; margin-left: 0; padding-left: 1rem; color: #8fa3bf; }
  hr { border: none; border-top: 1px solid #2a3b55; }
  nav.docs-nav { margin: 0 0 1.2rem; padding: 0.6rem 0; border-bottom: 1px solid #2a3b55;
                 font-size: 0.9rem; color: #8fa3bf; }
  nav.docs-nav a { margin-right: 0.75rem; }
  .mermaid-diagram { background: #141e2e; border: 1px solid #2a3b55; border-radius: 10px;
         padding: 1rem; margin: 1.2rem 0; overflow-x: auto; text-align: center; }
  .mermaid-diagram svg { max-width: 100%; height: auto; }
"""


_EDGE_RE = re.compile(
    r"(?P<src>[A-Za-z]\w*)(?:\[(?P<slabel>[^\]]*)\])?\s*"
    r"(?P<op>-->|-\.->)\s*"
    r"(?P<dst>[A-Za-z]\w*)(?:\[(?P<dlabel>[^\]]*)\])?"
)
_NODE_RE = re.compile(r"([A-Za-z]\w*)\[([^\]]*)\]")


def _mermaid_label_html(label: str) -> list[str]:
    """Convierte etiqueta Mermaid (con <br/>) a líneas de texto."""
    text = label.replace("<br/>", "\n").replace("<br>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    return [ln.strip() for ln in text.split("\n") if ln.strip()] or [""]


def _parse_mermaid_flowchart(
    code: str,
) -> tuple[str, dict[str, str], list[tuple[str, str, bool]]]:
    direction = "TD"
    nodes: dict[str, str] = {}
    edges: list[tuple[str, str, bool]] = []

    for raw_line in code.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        if line.lower().startswith("flowchart"):
            parts = line.split()
            if len(parts) > 1:
                direction = parts[1].upper()
            continue
        for m in _NODE_RE.finditer(line):
            nodes[m.group(1)] = m.group(2)
        for m in _EDGE_RE.finditer(line):
            src, dst = m.group("src"), m.group("dst")
            if m.group("slabel") is not None:
                nodes[src] = m.group("slabel")
            if m.group("dlabel") is not None:
                nodes[dst] = m.group("dlabel")
            nodes.setdefault(src, src)
            nodes.setdefault(dst, dst)
            edges.append((src, dst, m.group("op") == "-.->"))

    return direction, nodes, edges


def _mermaid_to_svg(code: str) -> str:
    """Renderiza flowchart Mermaid simple a SVG (sin JS; funciona en tkinterweb)."""
    direction, nodes, edges = _parse_mermaid_flowchart(code)
    if not nodes:
        return f"<pre>{html.escape(code)}</pre>"

    # Niveles por BFS desde raíces
    incoming: dict[str, int] = {n: 0 for n in nodes}
    children: dict[str, list[str]] = {n: [] for n in nodes}
    for src, dst, _ in edges:
        incoming[dst] = incoming.get(dst, 0) + 1
        children.setdefault(src, []).append(dst)
        incoming.setdefault(src, 0)
        children.setdefault(dst, [])

    roots = [n for n, c in incoming.items() if c == 0] or list(nodes.keys())[:1]
    level_of: dict[str, int] = {}
    queue = list(roots)
    for r in roots:
        level_of[r] = 0
    i = 0
    while i < len(queue):
        cur = queue[i]
        i += 1
        for ch in children.get(cur, []):
            nxt = level_of[cur] + 1
            if ch not in level_of or nxt > level_of[ch]:
                # prefer deeper placement when multiple paths
                if ch not in level_of:
                    queue.append(ch)
                level_of[ch] = max(level_of.get(ch, 0), nxt)

    for n in nodes:
        level_of.setdefault(n, 0)

    levels: dict[int, list[str]] = {}
    for n, lv in level_of.items():
        levels.setdefault(lv, []).append(n)
    for lv in levels:
        levels[lv].sort()

    max_level = max(levels) if levels else 0
    max_width = max(len(v) for v in levels.values()) if levels else 1

    box_w, box_h = 168, 58
    gap_x, gap_y = 36, 42
    pad = 24

    if direction in {"LR", "RL"}:
        width = pad * 2 + (max_level + 1) * box_w + max_level * gap_x
        height = pad * 2 + max_width * box_h + (max_width - 1) * gap_y
    else:
        width = pad * 2 + max_width * box_w + (max_width - 1) * gap_x
        height = pad * 2 + (max_level + 1) * box_h + max_level * gap_y

    pos: dict[str, tuple[float, float]] = {}
    for lv, ids in levels.items():
        n_at = len(ids)
        for idx, nid in enumerate(ids):
            if direction in {"LR", "RL"}:
                x = pad + lv * (box_w + gap_x)
                span = n_at * box_h + (n_at - 1) * gap_y
                y0 = pad + (height - 2 * pad - span) / 2
                y = y0 + idx * (box_h + gap_y)
            else:
                y = pad + lv * (box_h + gap_y)
                span = n_at * box_w + (n_at - 1) * gap_x
                x0 = pad + (width - 2 * pad - span) / 2
                x = x0 + idx * (box_w + gap_x)
            pos[nid] = (x, y)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" '
        f'viewBox="0 0 {int(width)} {int(height)}">',
        "<defs>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8fa3bf"/></marker>'
        "</defs>",
    ]

    for src, dst, dashed in edges:
        if src not in pos or dst not in pos:
            continue
        x1, y1 = pos[src]
        x2, y2 = pos[dst]
        # centros / bordes
        cx1, cy1 = x1 + box_w / 2, y1 + box_h / 2
        cx2, cy2 = x2 + box_w / 2, y2 + box_h / 2
        if direction in {"LR", "RL"}:
            sx, sy = x1 + box_w, cy1
            ex, ey = x2, cy2
        else:
            sx, sy = cx1, y1 + box_h
            ex, ey = cx2, y2
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="#8fa3bf" stroke-width="2"{dash} marker-end="url(#arrow)"/>'
        )

    for nid, (x, y) in pos.items():
        label_lines = _mermaid_label_html(nodes.get(nid, nid))
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_w}" height="{box_h}" rx="10" ry="10" '
            f'fill="#1a2740" stroke="#4ec4e0" stroke-width="1.5"/>'
        )
        # texto centrado (máx 3 líneas)
        lines = label_lines[:3]
        line_h = 14
        total_h = len(lines) * line_h
        ty = y + (box_h - total_h) / 2 + 11
        for li, ln in enumerate(lines):
            safe = html.escape(ln)
            if len(safe) > 22:
                safe = safe[:20] + "…"
            parts.append(
                f'<text x="{x + box_w / 2:.1f}" y="{ty + li * line_h:.1f}" '
                f'text-anchor="middle" fill="#e8eef7" font-size="12" '
                f'font-family="Segoe UI, system-ui, sans-serif">{safe}</text>'
            )

    parts.append("</svg>")
    return "\n".join(parts)


def _promote_mermaid_blocks(body: str) -> str:
    """Convierte bloques Mermaid a SVG estático (visible en GUI y navegador)."""

    pattern = re.compile(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        re.DOTALL | re.IGNORECASE,
    )

    def repl(match: re.Match[str]) -> str:
        code = html.unescape(match.group(1)).strip()
        try:
            svg = _mermaid_to_svg(code)
        except Exception:  # noqa: BLE001
            svg = f"<pre>{html.escape(code)}</pre>"
        return f'<div class="mermaid-diagram">{svg}</div>'

    return pattern.sub(repl, body)


def _md_file_to_html(md_path: Path, *, nav_links: list[tuple[str, str]] | None = None) -> str:
    """Markdown → HTML completo (extensiones: tablas, código, listas, Mermaid→SVG)."""
    import markdown as md_lib

    raw = md_path.read_text(encoding="utf-8")
    body = md_lib.markdown(
        raw,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists", "smarty"],
    )
    body = _rewrite_md_hrefs(body)
    body = _promote_mermaid_blocks(body)
    nav = ""
    if nav_links:
        items = " · ".join(
            f'<a href="{html.escape(href)}">{html.escape(label)}</a>' for label, href in nav_links
        )
        nav = f'<nav class="docs-nav">{items}</nav>'
    title = md_path.name
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>{_DOC_PAGE_CSS}</style>
</head><body>
{nav}
{body}
</body></html>
"""


def _docs_site_dir() -> Path:
    return Path(tempfile.gettempdir()) / "crism_gcpa_docs"


def _ensure_docs_site() -> Path:
    """Genera HTML de todos los .md en una carpeta temporal (enlaces relativos funcionales)."""
    out = _docs_site_dir()
    out.mkdir(parents=True, exist_ok=True)
    docs = sorted(_docs_dir().glob("*.md"))
    nav = [(p.stem.replace("_", " "), f"{p.stem}.html") for p in docs]
    for md_path in docs:
        html_path = out / f"{md_path.stem}.html"
        html_path.write_text(_md_file_to_html(md_path, nav_links=nav), encoding="utf-8")
    return out


def _html_for_doc(filename: str) -> Path:
    site = _ensure_docs_site()
    page = site / f"{Path(filename).stem}.html"
    if not page.is_file():
        raise FileNotFoundError(page)
    return page


class Worker:
    """Tareas en hilo secundario + cola de progreso/log hacia la UI."""

    def __init__(self) -> None:
        self._q: queue.Queue[tuple] = queue.Queue()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def run(self, label: str, fn: Callable[[], None]) -> None:
        if self._busy:
            messagebox.showwarning("Ocupado", "Ya hay una tarea en ejecución.")
            return
        self._busy = True
        self._q.put(("log", f"\n▶ {label}\n"))
        self._q.put(("progress", 0.0, "Iniciando…"))

        def target() -> None:
            try:
                fn()
                self._q.put(("progress", 1.0, "Completado"))
                self._q.put(("ok", f"✓ Completado: {label}"))
            except Exception as exc:  # noqa: BLE001
                self._q.put(("err", f"✗ Error: {exc}"))

        threading.Thread(target=target, daemon=True).start()

    def report_progress(self, _name: str, frac: float, msg: str) -> None:
        self._q.put(("progress", max(0.0, min(1.0, frac)), msg))

    def log(self, text: str) -> None:
        self._q.put(("log", text))

    def poll(self, app: "CrismApp") -> None:
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]
                if kind == "log":
                    app.append_log(item[1])
                elif kind == "progress":
                    app.set_progress(item[1], item[2])
                elif kind == "ok":
                    self._busy = False
                    app.append_log(item[1] + "\n")
                    app.set_status(item[1], ok=True)
                elif kind == "err":
                    self._busy = False
                    app.append_log(item[1] + "\n")
                    app.set_status(item[1], ok=False)
                    messagebox.showerror("Error", item[1])
        except queue.Empty:
            pass
        app.after(150, lambda: self.poll(app))


class PathRow(ctk.CTkFrame):
    def __init__(
        self,
        master,
        label: str,
        *,
        default: str = "",
        directory: bool = True,
        show_raw: bool = False,
        show_if: bool = False,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.var = ctk.StringVar(value=default)
        self._directory = directory
        self._on_change = on_change
        ctk.CTkLabel(self, text=label, width=110, anchor="w", text_color=COLORS["muted"]).pack(
            side="left"
        )
        entry = make_entry(self, textvariable=self.var, height=32)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(self, text="…", width=36, command=self._browse).pack(side="left")
        if show_raw:
            ctk.CTkButton(self, text="Raw", width=52, command=self._pick_raw).pack(
                side="left", padx=(6, 0)
            )
        if show_if:
            ctk.CTkButton(self, text="IF", width=40, command=self._pick_if).pack(
                side="left", padx=(6, 0)
            )
        if on_change:
            self.var.trace_add("write", lambda *_: on_change())

    def get(self) -> Path:
        return Path(self.var.get().strip())

    def _browse(self) -> None:
        if self._directory:
            path = filedialog.askdirectory(initialdir=self.var.get() or str(ROOT))
        else:
            path = filedialog.askopenfilename(initialdir=self.var.get() or str(ROOT))
        if path:
            self.var.set(path)

    def _pick_raw(self) -> None:
        products = _list_raw_products()
        if not products:
            messagebox.showinfo("Raw", f"No hay productos en {resolve_path('raw')}")
            return
        self._pick_from_list("Productos en data/raw", products)

    def _pick_if(self) -> None:
        from .io_if import list_if_products

        products = list_if_products()
        if not products:
            messagebox.showinfo(
                "IF",
                "No hay cubos IF en data/raw.\n"
                "Descarga con --data if o --data both.",
            )
            return
        self._pick_from_list("Productos IF en data/raw", products)

    def _pick_from_list(self, title: str, products: list[Path]) -> None:
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("520x360")
        win.transient(self.winfo_toplevel())
        box = ctk.CTkScrollableFrame(win)
        box.pack(fill="both", expand=True, padx=12, pady=12)

        def choose(p: Path) -> None:
            self.var.set(str(p))
            win.destroy()

        for p in products:
            ctk.CTkButton(
                box, text=p.name, anchor="w", fg_color=COLORS["card"], command=lambda p=p: choose(p)
            ).pack(fill="x", pady=3)


class CheckList(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        items: list[str],
        *,
        defaults: list[str] | None = None,
        on_change: Callable[[], None] | None = None,
        height: int = 140,
    ) -> None:
        super().__init__(master, height=height, fg_color=COLORS["card"])
        defaults = defaults if defaults is not None else items
        self._vars: dict[str, ctk.BooleanVar] = {}
        self._on_change = on_change
        cols = 3
        for i, item in enumerate(items):
            var = ctk.BooleanVar(value=item in defaults)
            self._vars[item] = var
            if on_change:
                var.trace_add("write", lambda *_: on_change())
            ctk.CTkCheckBox(self, text=item, variable=var, checkbox_width=18, checkbox_height=18).grid(
                row=i // cols, column=i % cols, sticky="w", padx=8, pady=4
            )
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=(len(items) + cols - 1) // cols, column=0, columnspan=cols, sticky="w", pady=6)
        ctk.CTkButton(btns, text="Todos", width=70, height=28, command=lambda: self._set_all(True)).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(
            btns, text="Ninguno", width=80, height=28, command=lambda: self._set_all(False)
        ).pack(side="left")

    def selected(self) -> list[str]:
        return [k for k, v in self._vars.items() if v.get()]

    def _set_all(self, value: bool) -> None:
        for v in self._vars.values():
            v.set(value)


class CrismApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CRISM Pipeline · GCPA")
        self.geometry("920x760")
        self.minsize(780, 640)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color=COLORS["bg"])

        self.worker = Worker()
        self.cli_var = ctk.StringVar(value="python -m crism_pipeline --help")
        self._build()
        self.worker.poll(self)

    def _build(self) -> None:
        self._build_header()
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self.tabs = ctk.CTkTabview(
            body,
            fg_color=COLORS["panel"],
            segmented_button_fg_color=COLORS["card"],
            segmented_button_selected_color=COLORS["accent_dim"],
            segmented_button_selected_hover_color=COLORS["accent"],
            text_color=COLORS["text"],
            command=self._on_tab_change,
        )
        self.tabs.pack(fill="both", expand=True)
        for name in _TAB_NAMES:
            self.tabs.add(name)

        self._build_download()
        self._build_export()
        self._build_maps()
        self._build_detect()
        self._build_classify()
        self._build_if_spectra()
        self._build_run()
        self._build_help()
        self._build_footer()
        self.tabs.set("Descarga")
        self._sync_active_cli()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=96)
        header.pack(fill="x")
        header.pack_propagate(False)

        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=12)

        logo_file = _logo_path()
        if logo_file.is_file():
            img = ctk.CTkImage(light_image=Image.open(logo_file), dark_image=Image.open(logo_file), size=(68, 68))
            ctk.CTkLabel(inner, image=img, text="").pack(side="left", padx=(0, 14))

        texts = ctk.CTkFrame(inner, fg_color="transparent")
        texts.pack(side="left", fill="y")
        ctk.CTkLabel(
            texts,
            text="GCPA",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=COLORS["accent"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            texts,
            text="Grupo de investigación en Ciencias Planetarias y Astrobiología",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["muted"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            texts,
            text="CRISM MTRDR SR · Viviano-Beck 2014",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(2, 0))

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(side="right")
        ctk.CTkButton(
            btns, text="Manual", width=90, height=32,
            command=lambda: self._show_doc("08_manual_gui.md"),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btns, text="Conceptos", width=100, height=32, fg_color=COLORS["card"],
            command=lambda: self._show_doc("01_conceptos.md"),
        ).pack(side="left", padx=4)

    def _build_footer(self) -> None:
        foot = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=12)
        foot.pack(fill="x", padx=16, pady=(0, 12))

        cli_row = ctk.CTkFrame(foot, fg_color="transparent")
        cli_row.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(cli_row, text="CLI equivalente", text_color=COLORS["muted"], width=120, anchor="w").pack(
            side="left"
        )
        make_entry(cli_row, textvariable=self.cli_var, readonly=True, height=30).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ctk.CTkButton(cli_row, text="Copiar", width=70, height=30, command=self._copy_cli).pack(side="left")

        prog = ctk.CTkFrame(foot, fg_color="transparent")
        prog.pack(fill="x", padx=12, pady=4)
        self.progress = ctk.CTkProgressBar(prog, height=14, progress_color=COLORS["accent"])
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress.set(0)
        self.pct_var = ctk.StringVar(value="0%")
        ctk.CTkLabel(prog, textvariable=self.pct_var, width=48, text_color=COLORS["accent"]).pack(
            side="left", padx=(8, 0)
        )

        self.progress_detail = ctk.StringVar(value="Listo")
        ctk.CTkLabel(
            foot, textvariable=self.progress_detail, text_color=COLORS["muted"], anchor="w"
        ).pack(fill="x", padx=12, pady=(0, 4))

        log_frame = ctk.CTkFrame(foot, fg_color="transparent")
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.log = ctk.CTkTextbox(log_frame, height=110, font=ctk.CTkFont(family="Consolas", size=12))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        enable_edit_context_menu(self.log, readonly=True)

        status = ctk.CTkFrame(foot, fg_color="transparent")
        status.pack(fill="x", padx=12, pady=(0, 10))
        self.status_var = ctk.StringVar(value=f"Raíz: {ROOT}")
        ctk.CTkLabel(status, textvariable=self.status_var, text_color=COLORS["muted"], anchor="w").pack(
            side="left", fill="x", expand=True
        )
        ctk.CTkButton(
            status, text="Abrir data/", width=100, height=28, fg_color=COLORS["card"],
            command=lambda: _open_path(ROOT / "data"),
        ).pack(side="right")

    # ── Descarga ──────────────────────────────────────────────────────────

    def _build_download(self) -> None:
        t = self.tabs.tab("Descarga")
        self.dl_mode = ctk.StringVar(value="ids_file")
        modes = ctk.CTkFrame(t, fg_color="transparent")
        modes.pack(fill="x", pady=(8, 4))
        for val, text in (
            ("ids_file", "SearchResults / IDs"),
            ("pdsid", "Product ID"),
            ("bbox", "Bounding box"),
        ):
            ctk.CTkRadioButton(
                modes, text=text, variable=self.dl_mode, value=val, command=self._sync_dl_cli
            ).pack(side="left", padx=(0, 14))

        self.dl_ids_file = PathRow(
            t,
            "Archivo IDs",
            default=str(ROOT / "product_ids.txt"),
            directory=False,
            on_change=self._sync_dl_cli,
        )
        self.dl_ids_file.pack(fill="x", pady=6)

        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="PDS ID", width=110, anchor="w", text_color=COLORS["muted"]).pack(side="left")
        self.dl_pdsid = ctk.StringVar()
        make_entry(row, textvariable=self.dl_pdsid).pack(side="left", fill="x", expand=True)
        self.dl_pdsid.trace_add("write", lambda *_: self._sync_dl_cli())

        bbox = ctk.CTkFrame(t, fg_color="transparent")
        bbox.pack(fill="x", pady=4)
        ctk.CTkLabel(bbox, text="BBox W E S N", width=110, anchor="w", text_color=COLORS["muted"]).pack(
            side="left"
        )
        self.dl_bbox = [ctk.StringVar() for _ in range(4)]
        for v in self.dl_bbox:
            make_entry(bbox, textvariable=v, width=90).pack(side="left", padx=3)
            v.trace_add("write", lambda *_: self._sync_dl_cli())

        self.dl_out = PathRow(
            t, "Salida", default=str(resolve_path("raw")), on_change=self._sync_dl_cli
        )
        self.dl_out.pack(fill="x", pady=6)

        data_row = ctk.CTkFrame(t, fg_color="transparent")
        data_row.pack(fill="x", pady=6)
        ctk.CTkLabel(
            data_row, text="Datos", width=110, anchor="w", text_color=COLORS["muted"]
        ).pack(side="left")
        self.dl_data = ctk.StringVar(value="sr")
        for val, text in (
            ("sr", "Solo SR (índices)"),
            ("if", "Solo IF (cubo I/F)"),
            ("both", "SR + IF"),
        ):
            ctk.CTkRadioButton(
                data_row,
                text=text,
                variable=self.dl_data,
                value=val,
                command=self._sync_dl_cli,
            ).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            t,
            text="IF es el cubo hiperespectral (mucho más pesado). El pipeline de mapas/detección usa SR.",
            text_color=COLORS["muted"],
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        row2 = ctk.CTkFrame(t, fg_color="transparent")
        row2.pack(fill="x", pady=4)
        ctk.CTkLabel(row2, text="Máx. productos", width=110, anchor="w", text_color=COLORS["muted"]).pack(
            side="left"
        )
        self.dl_max = ctk.StringVar()
        make_entry(row2, textvariable=self.dl_max, width=90).pack(side="left")
        self.dl_max.trace_add("write", lambda *_: self._sync_dl_cli())

        ctk.CTkButton(t, text="Descargar desde ODE", height=36, command=self._run_download).pack(
            anchor="e", pady=12
        )

    def _sync_dl_cli(self) -> None:
        if self.tabs.get() != "Descarga":
            return
        parts = ["python -m crism_pipeline download"]
        mode = self.dl_mode.get()
        if mode == "ids_file":
            parts += ["--ids-file", _q(self.dl_ids_file.var.get())]
        elif mode == "pdsid":
            parts += ["--pdsid", self.dl_pdsid.get() or "<ID>"]
        else:
            parts += ["--bbox", *[v.get() or "?" for v in self.dl_bbox]]
        data = self.dl_data.get()
        if data != "sr":
            parts += ["--data", data]
        if self.dl_out.var.get() and Path(self.dl_out.var.get()) != resolve_path("raw"):
            parts += ["--out", _q(self.dl_out.var.get())]
        if self.dl_max.get().strip():
            parts += ["--max-products", self.dl_max.get().strip()]
        self.cli_var.set(" ".join(parts))

    def _run_download(self) -> None:
        self._sync_dl_cli()
        mode = self.dl_mode.get()
        out = self.dl_out.get()
        max_p = int(self.dl_max.get()) if self.dl_max.get().strip() else None
        data = self.dl_data.get()
        on_prog = self.worker.report_progress

        def job() -> None:
            from .download import download_batch, download_scene, parse_ids_file

            self.worker.log(f"Tipo de datos: {data.upper()}\n")
            if mode == "ids_file":
                ids = parse_ids_file(self.dl_ids_file.get())
                if not ids:
                    raise ValueError("No se encontraron Product IDs en el archivo.")
                self.worker.log(f"IDs leídos ({len(ids)}): {', '.join(ids)}\n")
                paths = download_batch(ids, out, on_progress=on_prog, data=data)
            elif mode == "pdsid":
                pdsid = self.dl_pdsid.get().strip()
                if not pdsid:
                    raise ValueError("Indica un Product ID o patrón.")
                paths = download_scene(
                    pdsid=pdsid,
                    out_dir=out,
                    max_products=max_p,
                    on_progress=on_prog,
                    data=data,
                )
            else:
                try:
                    bbox = tuple(float(v.get()) for v in self.dl_bbox)
                except ValueError as exc:
                    raise ValueError("BBox inválido: usa 4 números W E S N.") from exc
                paths = download_scene(
                    bbox=bbox,
                    out_dir=out,
                    max_products=max_p,
                    on_progress=on_prog,
                    data=data,
                )
            self.worker.log(f"Archivos: {len(paths)} → {out}\n")

        self.worker.run("Descarga ODE", job)

    # ── Exportar ──────────────────────────────────────────────────────────

    def _build_export(self) -> None:
        t = self.tabs.tab("Exportar")
        self.ex_input = PathRow(t, "Entrada", show_raw=True, on_change=self._sync_export_cli)
        self.ex_input.pack(fill="x", pady=8)
        self.ex_out = PathRow(
            t, "Salida", default=str(resolve_path("processed")), on_change=self._sync_export_cli
        )
        self.ex_out.pack(fill="x", pady=6)
        ctk.CTkLabel(
            t,
            text="Exporta una copia GeoTIFF opcional (p. ej. QGIS). El flujo principal usa ENVI.",
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=8)
        ctk.CTkButton(t, text="Exportar GeoTIFF", height=36, command=self._run_export).pack(
            anchor="e", pady=8
        )

    def _sync_export_cli(self) -> None:
        if self.tabs.get() != "Exportar":
            return
        parts = ["python -m crism_pipeline export", "--input", _input_arg(self.ex_input.var.get())]
        if self.ex_out.var.get() and Path(self.ex_out.var.get()) != resolve_path("processed"):
            parts += ["--out", _q(self.ex_out.var.get())]
        self.cli_var.set(" ".join(parts))

    def _run_export(self) -> None:
        self._sync_export_cli()
        inp, out_root = self.ex_input.get(), self.ex_out.get()
        if not str(inp):
            messagebox.showerror("Exportar", "Selecciona un producto de entrada.")
            return

        def job() -> None:
            from .io_sr import export_geotiff, load_sr_cube

            self.worker.report_progress("export", 0.2, "Cargando cubo…")
            cube = load_sr_cube(inp)
            self.worker.report_progress("export", 0.6, f"Exportando {cube.product_id}…")
            tif = out_root / f"{cube.product_id}.tif"
            export_geotiff(cube, tif)
            self.worker.log(f"GeoTIFF: {tif}\nBandas: {len(cube.band_names)} | {cube.data.shape}\n")
            self.worker.report_progress("export", 1.0, "Exportación lista")

        self.worker.run("Exportar GeoTIFF", job)

    # ── Mapas ─────────────────────────────────────────────────────────────

    def _build_maps(self) -> None:
        t = self.tabs.tab("Mapas")
        self.mp_input = PathRow(t, "Entrada", show_raw=True, on_change=self._sync_maps_cli)
        self.mp_input.pack(fill="x", pady=8)
        self.mp_out = PathRow(
            t, "Salida", default=str(resolve_path("maps")), on_change=self._sync_maps_cli
        )
        self.mp_out.pack(fill="x", pady=6)
        ctk.CTkLabel(t, text="Browse products", text_color=COLORS["muted"]).pack(anchor="w", pady=(8, 4))
        self.mp_browse = CheckList(
            t, _browse_codes(), defaults=DEFAULT_BROWSE, on_change=self._sync_maps_cli
        )
        self.mp_browse.pack(fill="x", pady=4)
        ctk.CTkButton(t, text="Generar mapas", height=36, command=self._run_maps).pack(anchor="e", pady=10)

    def _sync_maps_cli(self) -> None:
        if self.tabs.get() != "Mapas":
            return
        browse = self.mp_browse.selected() or DEFAULT_BROWSE
        parts = ["python -m crism_pipeline maps", "--input", _input_arg(self.mp_input.var.get())]
        if self.mp_out.var.get() and Path(self.mp_out.var.get()) != resolve_path("maps"):
            parts += ["--out", _q(self.mp_out.var.get())]
        parts += ["--browse", *browse]
        self.cli_var.set(" ".join(parts))

    def _run_maps(self) -> None:
        self._sync_maps_cli()
        inp, out = self.mp_input.get(), self.mp_out.get()
        browse = self.mp_browse.selected()
        if not str(inp):
            messagebox.showerror("Mapas", "Selecciona un producto de entrada.")
            return
        if not browse:
            messagebox.showerror("Mapas", "Selecciona al menos un browse product.")
            return

        def job() -> None:
            from .maps import generate_all_maps

            n = len(browse)
            self.worker.report_progress("maps", 0.05, f"Generando {n} browse + índices…")
            paths = generate_all_maps(inp, out, browse_codes=browse)
            self.worker.log(f"Mapas generados: {len(paths)} → {out}\n")
            self.worker.report_progress("maps", 1.0, f"{len(paths)} archivos")

        self.worker.run("Generar mapas", job)

    # ── Detección ─────────────────────────────────────────────────────────

    def _build_detect(self) -> None:
        t = self.tabs.tab("Detección")
        self.dt_input = PathRow(t, "Entrada", show_raw=True, on_change=self._sync_detect_cli)
        self.dt_input.pack(fill="x", pady=8)
        self.dt_out = PathRow(
            t,
            "Salida",
            default=str(resolve_path("maps") / "detection"),
            on_change=self._sync_detect_cli,
        )
        self.dt_out.pack(fill="x", pady=6)
        ctk.CTkLabel(t, text="Minerales (vacío = todos)", text_color=COLORS["muted"]).pack(
            anchor="w", pady=(8, 4)
        )
        self.dt_minerals = CheckList(
            t, _mineral_keys(), defaults=[], on_change=self._sync_detect_cli
        )
        self.dt_minerals.pack(fill="x", pady=4)
        ctk.CTkButton(t, text="Detectar", height=36, command=self._run_detect).pack(anchor="e", pady=10)

    def _sync_detect_cli(self) -> None:
        if self.tabs.get() != "Detección":
            return
        parts = ["python -m crism_pipeline detect", "--input", _input_arg(self.dt_input.var.get())]
        default_out = resolve_path("maps") / "detection"
        if self.dt_out.var.get() and Path(self.dt_out.var.get()) != default_out:
            parts += ["--out", _q(self.dt_out.var.get())]
        minerals = self.dt_minerals.selected()
        if minerals:
            parts += ["--mineral", *minerals]
        self.cli_var.set(" ".join(parts))

    def _run_detect(self) -> None:
        self._sync_detect_cli()
        inp, out = self.dt_input.get(), self.dt_out.get()
        minerals = self.dt_minerals.selected() or None
        if not str(inp):
            messagebox.showerror("Detección", "Selecciona un producto de entrada.")
            return

        def job() -> None:
            from .detection import run_detection_pipeline

            keys = minerals or _mineral_keys()
            self.worker.report_progress("detect", 0.1, f"Detectando {len(keys)} minerales…")
            results = run_detection_pipeline(inp, out, minerals)
            for i, (key, res) in enumerate(results.items(), start=1):
                self.worker.log(f"  {key}: {res.coverage_pct:.2f}% cobertura\n")
                self.worker.report_progress(key, i / max(len(results), 1), f"{key}: {res.coverage_pct:.1f}%")
            self.worker.report_progress("detect", 1.0, "Detección lista")

        self.worker.run("Detección mineral", job)

    # ── Clasificación ─────────────────────────────────────────────────────

    def _build_classify(self) -> None:
        t = self.tabs.tab("Clasificación")
        self.cl_input = PathRow(t, "Entrada", show_raw=True, on_change=self._sync_classify_cli)
        self.cl_input.pack(fill="x", pady=8)
        self.cl_out = PathRow(
            t,
            "Salida",
            default=str(resolve_path("maps") / "classification"),
            on_change=self._sync_classify_cli,
        )
        self.cl_out.pack(fill="x", pady=6)

        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", pady=6)
        ctk.CTkLabel(row, text="Método", width=110, anchor="w", text_color=COLORS["muted"]).pack(side="left")
        self.cl_method = ctk.StringVar(value="kmeans")
        ctk.CTkOptionMenu(
            row,
            variable=self.cl_method,
            values=["kmeans", "signature", "supervised"],
            command=lambda _: self._sync_classify_cli(),
        ).pack(side="left")

        row2 = ctk.CTkFrame(t, fg_color="transparent")
        row2.pack(fill="x", pady=6)
        ctk.CTkLabel(row2, text="N clusters", width=110, anchor="w", text_color=COLORS["muted"]).pack(
            side="left"
        )
        self.cl_n = ctk.StringVar(value="5")
        make_entry(row2, textvariable=self.cl_n, width=80).pack(side="left")
        self.cl_n.trace_add("write", lambda *_: self._sync_classify_cli())

        self.cl_csv = PathRow(
            t,
            "Training CSV",
            default=str(ROOT / "examples" / "training_pixels.example.csv"),
            directory=False,
            on_change=self._sync_classify_cli,
        )
        self.cl_csv.pack(fill="x", pady=6)
        ctk.CTkButton(t, text="Clasificar", height=36, command=self._run_classify).pack(anchor="e", pady=10)

    def _sync_classify_cli(self) -> None:
        if self.tabs.get() != "Clasificación":
            return
        parts = ["python -m crism_pipeline classify", "--input", _input_arg(self.cl_input.var.get())]
        default_out = resolve_path("maps") / "classification"
        if self.cl_out.var.get() and Path(self.cl_out.var.get()) != default_out:
            parts += ["--out", _q(self.cl_out.var.get())]
        parts += ["--method", self.cl_method.get()]
        if self.cl_method.get() == "kmeans" and self.cl_n.get().strip():
            parts += ["--n-clusters", self.cl_n.get().strip()]
        if self.cl_method.get() == "supervised":
            parts += ["--training-csv", _q(self.cl_csv.var.get())]
        self.cli_var.set(" ".join(parts))

    def _run_classify(self) -> None:
        self._sync_classify_cli()
        inp, out = self.cl_input.get(), self.cl_out.get()
        method = self.cl_method.get()
        if not str(inp):
            messagebox.showerror("Clasificación", "Selecciona un producto de entrada.")
            return
        n_clusters = int(self.cl_n.get()) if self.cl_n.get().strip() else None
        training = self.cl_csv.get() if method == "supervised" else None
        if method == "supervised" and (not training or not training.is_file()):
            messagebox.showerror("Clasificación", "Indica un CSV de entrenamiento válido.")
            return

        def job() -> None:
            from .classification import run_classification_pipeline

            self.worker.report_progress("classify", 0.15, f"Clasificando ({method})…")
            run_classification_pipeline(
                inp, out, method=method, n_clusters=n_clusters, training_csv=training
            )
            self.worker.log(f"Clasificación guardada en {out}\n")
            self.worker.report_progress("classify", 1.0, "Clasificación lista")

        self.worker.run("Clasificación", job)

    # ── Espectros IF ──────────────────────────────────────────────────────

    def _build_if_spectra(self) -> None:
        t = self.tabs.tab("Espectros IF")
        self._if_cube = None
        self._if_mean = None
        self._if_pixel = None
        self._if_preview = None

        ctk.CTkLabel(
            t,
            text="Firmas espectrales del cubo I/F (hiperespectral). Clic en la imagen o indica line/sample.",
            text_color=COLORS["muted"],
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(8, 6))

        self.if_input = PathRow(
            t, "Cubo IF", show_if=True, on_change=self._sync_if_cli
        )
        self.if_input.pack(fill="x", pady=4)

        controls = ctk.CTkFrame(t, fg_color="transparent")
        controls.pack(fill="x", pady=6)
        ctk.CTkButton(controls, text="Cargar IF", width=110, command=self._load_if_cube).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkLabel(controls, text="Line", text_color=COLORS["muted"]).pack(side="left", padx=(8, 4))
        self.if_line = ctk.StringVar(value="0")
        make_entry(controls, textvariable=self.if_line, width=70).pack(side="left")
        ctk.CTkLabel(controls, text="Sample", text_color=COLORS["muted"]).pack(side="left", padx=(8, 4))
        self.if_sample = ctk.StringVar(value="0")
        make_entry(controls, textvariable=self.if_sample, width=70).pack(side="left")
        ctk.CTkButton(
            controls, text="Espectro píxel", width=120, command=self._plot_if_pixel
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            controls, text="Media escena", width=120, command=self._plot_if_mean
        ).pack(side="left", padx=4)

        self.if_show_pixel = ctk.BooleanVar(value=True)
        self.if_show_mean = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            controls, text="Mostrar píxel", variable=self.if_show_pixel, command=self._redraw_if_plot
        ).pack(side="left", padx=(12, 4))
        ctk.CTkCheckBox(
            controls, text="Mostrar media", variable=self.if_show_mean, command=self._redraw_if_plot
        ).pack(side="left", padx=4)

        export_row = ctk.CTkFrame(t, fg_color="transparent")
        export_row.pack(fill="x", pady=4)
        ctk.CTkButton(
            export_row, text="Exportar CSV…", width=130, command=self._export_if_csv
        ).pack(side="left")
        self.if_status = ctk.StringVar(value="Sin cubo IF cargado")
        ctk.CTkLabel(
            export_row, textvariable=self.if_status, text_color=COLORS["muted"], anchor="w"
        ).pack(side="left", padx=12)

        panes = ctk.CTkFrame(t, fg_color="transparent")
        panes.pack(fill="both", expand=True, pady=8)

        # Vista previa (matplotlib)
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        left = ctk.CTkFrame(panes, fg_color=COLORS["card"], corner_radius=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ctk.CTkLabel(left, text="Vista previa (clic = píxel)", text_color=COLORS["accent"]).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        self._if_fig_img = Figure(figsize=(4.2, 3.6), dpi=100, facecolor=COLORS["card"])
        self._if_ax_img = self._if_fig_img.add_subplot(111)
        self._if_ax_img.set_facecolor(COLORS["panel"])
        self._if_ax_img.axis("off")
        self._if_canvas_img = FigureCanvasTkAgg(self._if_fig_img, master=left)
        self._if_canvas_img.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)
        self._if_canvas_img.mpl_connect("button_press_event", self._on_if_image_click)

        right = ctk.CTkFrame(panes, fg_color=COLORS["card"], corner_radius=8)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ctk.CTkLabel(right, text="Firma espectral I/F", text_color=COLORS["accent"]).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        self._if_fig_spec = Figure(figsize=(5.2, 3.6), dpi=100, facecolor=COLORS["card"])
        self._if_ax_spec = self._if_fig_spec.add_subplot(111)
        self._style_if_spectrum_ax()
        self._if_canvas_spec = FigureCanvasTkAgg(self._if_fig_spec, master=right)
        self._if_canvas_spec.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)

        self._sync_if_cli()

    def _style_if_spectrum_ax(self) -> None:
        ax = self._if_ax_spec
        ax.set_facecolor(COLORS["panel"])
        ax.tick_params(colors=COLORS["muted"])
        for spine in ax.spines.values():
            spine.set_color(COLORS["border"])
        ax.set_xlabel("Longitud de onda (nm)", color=COLORS["muted"])
        ax.set_ylabel("I/F", color=COLORS["muted"])
        ax.grid(True, alpha=0.25, color=COLORS["border"])

    def _sync_if_cli(self) -> None:
        if self.tabs.get() != "Espectros IF":
            return
        path = self.if_input.var.get() or "<dir_if>"
        self.cli_var.set(
            f"# Espectros IF (GUI) — cubo: {path}  |  "
            f"line={self.if_line.get()} sample={self.if_sample.get()}"
        )

    def _load_if_cube(self) -> None:
        if not self.if_input.var.get().strip():
            messagebox.showerror("IF", "Selecciona un directorio con cubo IF.")
            return
        path = self.if_input.get()

        def job() -> None:
            from .io_if import load_if_cube

            self.worker.report_progress("if", 0.1, "Cargando cubo IF…")
            cube = load_if_cube(path)
            self.worker.report_progress("if", 0.55, "Calculando media espectral…")
            mean = cube.mean_spectrum()
            self.worker.report_progress("if", 0.8, "Generando vista previa…")
            preview = cube.quicklook_rgb()

            def apply() -> None:
                self._if_cube = cube
                self._if_mean = mean
                self._if_pixel = None
                self._if_preview = preview
                self.if_line.set(str(cube.lines // 2))
                self.if_sample.set(str(cube.samples // 2))
                self.if_status.set(
                    f"{cube.product_id} · {cube.lines}×{cube.samples}×{cube.nbands} · "
                    f"{cube.wavelengths[0]:.0f}–{cube.wavelengths[-1]:.0f} nm"
                )
                self._draw_if_preview()
                self._plot_if_pixel()
                self.worker.log(
                    f"IF cargado: {cube.product_id} ({cube.nbands} bandas)\n"
                )
                self._sync_if_cli()

            self.after(0, apply)
            self.worker.report_progress("if", 1.0, "IF listo")

        self.worker.run("Cargar cubo IF", job)

    def _draw_if_preview(self, *, line: int | None = None, sample: int | None = None) -> None:
        if self._if_preview is None:
            return
        ax = self._if_ax_img
        ax.clear()
        ax.imshow(self._if_preview, interpolation="nearest")
        if line is not None and sample is not None:
            ax.plot(
                [sample],
                [line],
                "o",
                color=COLORS["accent"],
                markersize=8,
                markeredgecolor="white",
                markeredgewidth=1.2,
            )
        ax.set_title("Clic para seleccionar píxel", color=COLORS["muted"], fontsize=9)
        ax.axis("off")
        self._if_fig_img.tight_layout()
        self._if_canvas_img.draw_idle()

    def _on_if_image_click(self, event) -> None:
        if self._if_cube is None or event.inaxes != self._if_ax_img:
            return
        if event.xdata is None or event.ydata is None:
            return
        sample = int(round(event.xdata))
        line = int(round(event.ydata))
        sample = max(0, min(self._if_cube.samples - 1, sample))
        line = max(0, min(self._if_cube.lines - 1, line))
        self.if_line.set(str(line))
        self.if_sample.set(str(sample))
        self._plot_if_pixel()

    def _plot_if_pixel(self) -> None:
        if self._if_cube is None:
            messagebox.showwarning("IF", "Carga un cubo IF primero.")
            return
        try:
            line = int(self.if_line.get())
            sample = int(self.if_sample.get())
        except ValueError:
            messagebox.showerror("IF", "Line y Sample deben ser enteros.")
            return
        try:
            self._if_pixel = self._if_cube.spectrum_at(line, sample)
        except IndexError as exc:
            messagebox.showerror("IF", str(exc))
            return

        self._draw_if_preview(line=line, sample=sample)
        self._redraw_if_plot()
        self._sync_if_cli()

    def _plot_if_mean(self) -> None:
        if self._if_cube is None:
            messagebox.showwarning("IF", "Carga un cubo IF primero.")
            return
        if self._if_mean is None:
            self._if_mean = self._if_cube.mean_spectrum()
        self.if_show_mean.set(True)
        self._redraw_if_plot()

    def _redraw_if_plot(self) -> None:
        if self._if_cube is None:
            return
        ax = self._if_ax_spec
        ax.clear()
        self._style_if_spectrum_ax()
        wl = self._if_cube.wavelengths
        plotted = False
        if self.if_show_pixel.get() and self._if_pixel is not None:
            ax.plot(
                wl,
                self._if_pixel,
                color=COLORS["accent"],
                lw=1.4,
                label=f"Píxel ({self.if_line.get()},{self.if_sample.get()})",
            )
            plotted = True
        if self.if_show_mean.get() and self._if_mean is not None:
            ax.plot(
                wl,
                self._if_mean,
                color=COLORS["warn"],
                lw=1.6,
                alpha=0.9,
                label="Media escena",
            )
            plotted = True
        if plotted:
            ax.legend(facecolor=COLORS["card"], edgecolor=COLORS["border"], labelcolor=COLORS["text"])
        ax.set_title(self._if_cube.product_id, color=COLORS["text"], fontsize=10)
        self._if_fig_spec.tight_layout()
        self._if_canvas_spec.draw_idle()

    def _export_if_csv(self) -> None:
        if self._if_cube is None:
            messagebox.showwarning("IF", "Carga un cubo IF primero.")
            return
        pixel = self._if_pixel
        mean = self._if_mean
        if pixel is None and mean is None:
            messagebox.showerror(
                "CSV",
                "No hay espectros para exportar.\n"
                "Carga el cubo y selecciona un píxel (o usa «Media escena»).",
            )
            return
        default = f"{self._if_cube.product_id}_spectra.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=default,
            initialdir=str(resolve_path("maps")),
        )
        if not path:
            return
        line = sample = None
        if pixel is not None:
            try:
                line = int(self.if_line.get())
                sample = int(self.if_sample.get())
            except ValueError:
                line = sample = None

        from .io_if import export_spectra_csv

        out = export_spectra_csv(
            Path(path),
            self._if_cube.wavelengths,
            pixel=pixel,
            mean=mean,
            line=line,
            sample=sample,
            product_id=self._if_cube.product_id,
        )
        self.if_status.set(f"CSV exportado: {out.name}")
        self.worker.log(f"CSV espectros IF → {out}\n")
        messagebox.showinfo("CSV", f"Guardado:\n{out}")

    # ── Pipeline ──────────────────────────────────────────────────────────

    def _build_run(self) -> None:
        t = self.tabs.tab("Pipeline")
        ctk.CTkLabel(
            t,
            text="Ejecuta maps + detect + classify sobre un cubo ENVI (sin conversión intermedia).",
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(8, 10))
        self.run_input = PathRow(t, "Entrada", show_raw=True, on_change=self._sync_run_cli)
        self.run_input.pack(fill="x", pady=6)

        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", pady=6)
        ctk.CTkLabel(row, text="Método", width=110, anchor="w", text_color=COLORS["muted"]).pack(side="left")
        self.run_method = ctk.StringVar(value="kmeans")
        ctk.CTkOptionMenu(
            row,
            variable=self.run_method,
            values=["kmeans", "signature"],
            command=lambda _: self._sync_run_cli(),
        ).pack(side="left")

        row2 = ctk.CTkFrame(t, fg_color="transparent")
        row2.pack(fill="x", pady=6)
        ctk.CTkLabel(row2, text="N clusters", width=110, anchor="w", text_color=COLORS["muted"]).pack(
            side="left"
        )
        self.run_n = ctk.StringVar(value="5")
        make_entry(row2, textvariable=self.run_n, width=80).pack(side="left")
        self.run_n.trace_add("write", lambda *_: self._sync_run_cli())

        ctk.CTkButton(t, text="Ejecutar pipeline completo", height=36, command=self._run_pipeline).pack(
            anchor="e", pady=12
        )

    def _sync_run_cli(self) -> None:
        if self.tabs.get() != "Pipeline":
            return
        self.cli_var.set(
            " ".join(
                [
                    "python -m crism_pipeline run",
                    "--input",
                    _input_arg(self.run_input.var.get()),
                    "--method",
                    self.run_method.get(),
                    "--n-clusters",
                    self.run_n.get() or "5",
                ]
            )
        )

    def _run_pipeline(self) -> None:
        self._sync_run_cli()
        inp = self.run_input.get()
        if not str(inp):
            messagebox.showerror("Pipeline", "Selecciona un producto de entrada.")
            return
        method = self.run_method.get()
        n_clusters = int(self.run_n.get()) if self.run_n.get().strip() else 5

        def job() -> None:
            from .classification import run_classification_pipeline
            from .detection import run_detection_pipeline
            from .io_sr import load_sr_cube
            from .maps import generate_all_maps

            self.worker.report_progress("run", 0.05, "Cargando cubo…")
            cube = load_sr_cube(inp)
            maps_dir = resolve_path("maps") / cube.product_id
            self.worker.log(f"Producto: {cube.product_id}\n")
            self.worker.report_progress("run", 0.25, "Mapas…")
            generate_all_maps(inp, maps_dir)
            self.worker.report_progress("run", 0.55, "Detección…")
            run_detection_pipeline(inp, maps_dir / "detection")
            self.worker.report_progress("run", 0.8, "Clasificación…")
            run_classification_pipeline(
                inp, maps_dir / "classification", method=method, n_clusters=n_clusters
            )
            self.worker.log(f"Salidas en {maps_dir}\n")
            self.worker.report_progress("run", 1.0, "Pipeline completo")

        self.worker.run("Pipeline completo", job)

    # ── Ayuda / documentación ─────────────────────────────────────────────

    def _build_help(self) -> None:
        t = self.tabs.tab("Ayuda")
        ctk.CTkLabel(
            t,
            text="Documentación del pipeline y de esta interfaz",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(
            t,
            text="Ver: HTML renderizado en la app (enlaces clicables).  Abrir: mismo sitio en el navegador.",
            text_color=COLORS["muted"],
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        grid = ctk.CTkScrollableFrame(t, fg_color=COLORS["card"], height=360)
        grid.pack(fill="both", expand=True)

        for title, fname in DOCS:
            row = ctk.CTkFrame(grid, fg_color="transparent")
            row.pack(fill="x", pady=4, padx=8)
            ctk.CTkLabel(row, text=title, anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row, text="Ver", width=70, height=28, command=lambda f=fname: self._show_doc(f)
            ).pack(side="right", padx=4)
            ctk.CTkButton(
                row,
                text="Abrir",
                width=70,
                height=28,
                fg_color=COLORS["accent_dim"],
                command=lambda f=fname: self._open_doc(f),
            ).pack(side="right")

        ctk.CTkButton(
            t, text="Abrir carpeta docs/", height=32, fg_color=COLORS["card"],
            command=lambda: _open_path(_docs_dir()),
        ).pack(anchor="e", pady=10)

    def _on_tab_change(self) -> None:
        self._sync_active_cli()

    def _sync_active_cli(self) -> None:
        tab = self.tabs.get()
        syncers = {
            "Descarga": self._sync_dl_cli,
            "Exportar": self._sync_export_cli,
            "Mapas": self._sync_maps_cli,
            "Detección": self._sync_detect_cli,
            "Clasificación": self._sync_classify_cli,
            "Espectros IF": self._sync_if_cli,
            "Pipeline": self._sync_run_cli,
            "Ayuda": lambda: self.cli_var.set(
                "python -m crism_pipeline --help  # ver docs/08_manual_gui.md"
            ),
        }
        fn = syncers.get(tab)
        if fn:
            fn()

    def _doc_path(self, filename: str) -> Path:
        return (_docs_dir() / filename).resolve()

    def _open_doc(self, filename: str) -> None:
        """Abre el documento renderizado (HTML) en el navegador, con enlaces entre docs."""
        path = self._doc_path(filename)
        if not path.is_file():
            messagebox.showerror("Documentación", f"No existe:\n{path}")
            return
        try:
            page = _html_for_doc(filename)
            webbrowser.open(page.as_uri())
            self.status_var.set(f"Navegador: {page.name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Documentación", str(exc))
            self._show_doc(filename)

    def _show_doc(self, filename: str) -> None:
        """Vista HTML renderizada dentro de la aplicación (tkinterweb)."""
        path = self._doc_path(filename)
        if not path.is_file():
            messagebox.showerror("Documentación", f"No existe:\n{path}")
            return
        try:
            page = _html_for_doc(filename)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Documentación", str(exc))
            return

        win = ctk.CTkToplevel(self)
        win.title(f"GCPA · {filename}")
        win.geometry("860x640")
        win.configure(fg_color=COLORS["bg"])
        win.after(10, win.lift)
        win.after(20, win.focus_force)

        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))

        nav = ctk.CTkFrame(top, fg_color="transparent")
        nav.pack(side="left", fill="x", expand=True)

        history: list[Path] = []
        current_page = {"path": page.resolve()}

        back_btn = ctk.CTkButton(
            nav,
            text="← Atrás",
            width=90,
            height=28,
            fg_color=COLORS["card"],
            state="disabled",
        )
        back_btn.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            nav,
            text=page.name,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["accent"],
        )
        title_lbl.pack(side="left")
        current_stem = {"name": Path(filename).stem}

        def open_current_in_browser() -> None:
            self._open_doc(f"{current_stem['name']}.md")

        ctk.CTkButton(
            top,
            text="Abrir en navegador",
            width=150,
            height=28,
            command=open_current_in_browser,
        ).pack(side="right")

        try:
            import os
            import tkinter as tk
            from urllib.parse import unquote, urlparse

            from tkinterweb import HtmlFrame

            holder = tk.Frame(win, bg=COLORS["bg"])
            holder.pack(fill="both", expand=True, padx=8, pady=(0, 8))

            def _file_from_url(url: str) -> Path | None:
                parsed = urlparse(url)
                if parsed.scheme in {"http", "https", "mailto"}:
                    return None
                if parsed.scheme == "file" or url.startswith("file:"):
                    raw = unquote(parsed.path or "")
                    # Windows: file:///C:/... → path /C:/...
                    if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw):
                        raw = raw[1:]
                    local = Path(raw)
                else:
                    # relativo o nombre suelto
                    name = Path(unquote(url.split("#", 1)[0])).name
                    if not name:
                        return None
                    local = _docs_site_dir() / name
                if local.suffix.lower() == ".md":
                    local = local.with_suffix(".html")
                return local if local.is_file() else None

            def _show_local(local: Path, *, push_history: bool) -> None:
                local = local.resolve()
                if push_history and current_page["path"] != local:
                    history.append(current_page["path"])
                    back_btn.configure(state="normal")
                frame.load_url(local.as_uri())
                current_page["path"] = local
                title_lbl.configure(text=local.name)
                current_stem["name"] = local.stem
                win.title(f"GCPA · {local.name}")
                self.status_var.set(f"Documento: {local.name}")

            def go_back() -> None:
                if not history:
                    back_btn.configure(state="disabled")
                    return
                prev = history.pop()
                _show_local(prev, push_history=False)
                if not history:
                    back_btn.configure(state="disabled")

            back_btn.configure(command=go_back)

            def on_link_click(url: str) -> None:
                """Navegación fiable: externos → navegador; locales → load_url(as_uri)."""
                if not url:
                    return
                if url.startswith(("http://", "https://", "mailto:")):
                    webbrowser.open(url)
                    return
                # anclas en la misma página
                if url.startswith("#"):
                    try:
                        frame.load_url(frame.current_url.split("#", 1)[0] + url)
                    except Exception:  # noqa: BLE001
                        pass
                    return
                local = _file_from_url(url)
                if local is None:
                    # intentar resolver respecto al sitio de docs
                    name = Path(urlparse(url).path).name or Path(url).name
                    if name.lower().endswith(".md"):
                        name = f"{name[:-3]}.html"
                    candidate = _docs_site_dir() / name
                    local = candidate if candidate.is_file() else None
                if local is not None and local.is_file():
                    _show_local(local, push_history=True)
                else:
                    messagebox.showwarning(
                        "Enlace",
                        f"No se pudo abrir el enlace:\n{url}",
                        parent=win,
                    )

            frame = HtmlFrame(
                holder,
                messages_enabled=False,
                horizontal_scrollbar="auto",
                on_link_click=on_link_click,
            )
            frame.pack(fill="both", expand=True)
            # as_uri() evita el bug file://C:\... de load_file en Windows
            frame.load_url(page.resolve().as_uri())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Visor HTML",
                f"No se pudo cargar el visor integrado ({exc}).\nSe abrirá en el navegador.",
            )
            self._open_doc(filename)
            win.destroy()
            return

        self.status_var.set(f"Documento: {filename}")

    # ── UI helpers ────────────────────────────────────────────────────────

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_progress(self, frac: float, detail: str) -> None:
        frac = max(0.0, min(1.0, float(frac)))
        self.progress.set(frac)
        self.pct_var.set(f"{int(round(frac * 100))}%")
        self.progress_detail.set(detail)

    def set_status(self, msg: str, *, ok: bool) -> None:
        self.status_var.set(msg)
        if ok:
            self.set_progress(1.0, msg)

    def _copy_cli(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.cli_var.get())
        self.status_var.set("Comando CLI copiado")


def main() -> int:
    # Pillow es dependencia de CustomTkinter para CTkImage
    app = CrismApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
