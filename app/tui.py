#!/usr/bin/env python3
"""ArcOps TUI — Spotify-like dashboard. Run: python -m app.tui (or arcops tui).

Pure presentation layer: renders the dashboard and delegates every AWS
call and all inference to the shared engine (``cloudops_fc.core``). No AWS
or model logic lives here — the engine stays the single source of truth.

Layout (three columns + bottom bar):
- Left: brand, LocalStack status badge, model info, tools, bindings.
- Center: resources DataTable (zebra rows, accent header, colored types).
- Right: search panel — prompt Input, last-result, quick actions.
- Bottom: persistent status line + indeterminate progress bar during
  blocking work (model load ~30s, LocalStack boot, refreshes).

Blocking work runs in Textual workers so the interface never freezes.
Targets LocalStack by default; real AWS mode is opt-in via ``ARC_OPS_REAL=1``
and every destructive action requires an explicit on-screen confirmation.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.dom import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Static,
)

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloudops_fc.core import (  # noqa: E402
    REAL,
    act,
    create,
    get_all,
    ls_check,
    tag_it,
)

LS_START_TIME: float | None = None  # When LocalStack was started (by this TUI)


def _fmt_duration(seconds: int) -> str:
    """Human-readable duration: '42s', '5m', '1h 23m', '2d 4h'."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


def _ls_uptime() -> int | None:
    """Seconds since the LocalStack container started, or None if unknown.

    Prefers the container's real start time (handles LocalStack already
    running before the TUI opened); falls back to the in-session start.
    """
    if LS_START_TIME is not None:
        return int(time.time() - LS_START_TIME)
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.StartedAt}}", "localstack"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            started = datetime.fromisoformat(r.stdout.strip().replace("Z", "+00:00"))
            return int(time.time() - started.timestamp())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


# ── Palette (mirrors the inline CSS) ─────────────────────────────────────
C_ACCENT = "#e89a6b"
C_OK = "#7ee787"
C_ERROR = "#ff6b6b"
C_TEXT = "#eeeeee"


def _configure_stdio() -> None:
    """Make stdout/stderr UTF-8 on Windows consoles (cp1252 can't encode •)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _suppress_core_printing() -> contextlib.AbstractContextManager[Any]:
    """Swallow engine ``print()`` chatter while the TUI owns the screen.

    The engine (core) reports everything through return values; only the
    TUI's own notifications are shown to the user.
    """
    return contextlib.redirect_stdout(io.StringIO())


class _Waiter:
    """Single-shot bridge between a worker thread and a modal question."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.ok = False
        self.resolved = False


class InputScreen(ModalScreen[str | None]):
    """Modal that collects a single string value from the user."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str, placeholder: str, submit_label: str) -> None:
        super().__init__()
        self._label = label
        self._placeholder = placeholder
        self._submit_label = submit_label

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Label(self._label)
            yield Input(placeholder=self._placeholder, id="input-value")
            with Horizontal(classes="modal-buttons"):
                yield Button(self._submit_label, id="submit", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#input-value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def _on_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            value = self.query_one("#input-value", Input).value.strip()
            self.dismiss(value or None)
        else:
            self.dismiss(None)


class ArcOpsApp(App):
    """ArcOps terminal dashboard — Spotify-like three-panel layout."""

    TITLE = "ArcOps"
    SUBTITLE = "Natural language -> AWS"
    THEME = "catppuccin-mocha"

    CSS = """
    /* ── Root ─────────────────────────────────────────────────────────── */
    Screen { background: #080808; }

    /* ── Main three-column row ────────────────────────────────────────── */
    #main-row { height: 1fr; }
    #side-left {
        width: 36; height: 1fr;
        border: round #222222;
        background: #080808;
        padding: 1 0;
    }
    #resources {
        width: 1fr; height: 1fr;
        border: round #e89a6b;
        background: #080808;
    }
    #side-right {
        width: 44; height: 1fr;
        border: round #e89a6b;
        background: #080808;
        padding: 1 1;
    }

    /* ── Responsive modes (toggled from on_resize) ────────────────────── */
    #main-row.responsive-stack { layout: vertical; height: auto; }
    #main-row.responsive-stack #side-left { width: 1fr; height: auto; }
    #main-row.responsive-stack #resources { width: 1fr; height: 22; }
    #main-row.responsive-stack #side-right { width: 1fr; height: auto; }
    #main-row.responsive-compact #model-info { display: none; }
    #main-row.responsive-compact #resources { height: 14; }
    #main-row.responsive-compact #quick-actions { height: 5; }

    /* ── Left panel ───────────────────────────────────────────────────── */
    #brand { color: #e89a6b; text-style: bold; padding: 0 1; }
    #subtitle { color: #777777; padding: 0 1; }
    #ls-badge { padding: 1 1 0 1; }
    #model-info { color: #777777; padding: 0 1; }
    .panel-heading { color: #e89a6b; text-style: bold; padding: 1 1 0 1; }
    .muted { color: #777777; padding: 0 1; }

    /* ── Center DataTable ─────────────────────────────────────────────── */
    #resources > .datatable--header {
        background: #1a1a1a;
        color: #e89a6b;
        text-style: bold;
    }
    #resources > .datatable--odd-row { background: #0d0d0d; }
    #resources > .datatable--even-row { background: #080808; }
    #resources > .datatable--cursor { background: #555555; color: #eeeeee; }

    /* ── Right search panel ───────────────────────────────────────────── */
    #search-title { color: #e89a6b; text-style: bold; padding: 0 1; }
    #search-input {
        border: round #555555;
        background: #111111;
        margin-top: 1;
    }
    #search-input:focus { border: round #e89a6b; }
    #last-result { color: #eeeeee; padding: 1 1 0 1; }
    #quick-actions { height: 8; border: none; margin: 0 1; }
    #quick-actions > ListItem {
        background: #080808;
        padding: 0 1;
        color: #eeeeee;
    }
    #quick-actions > ListItem:hover { background: #555555; }

    /* ── Bottom status + progress ─────────────────────────────────────── */
    #status { padding: 0 2; text-style: bold; background: #111111; height: 1; }
    #progress { display: none; height: 1; }
    #progress > .bar--indeterminate { background: #e89a6b; }
    .status-ok { color: #7ee787; }
    .status-warn { color: #e89a6b; }
    .status-error { color: #ff6b6b; }
    .status-busy { color: #e89a6b; }
    .status-neutral { color: #eeeeee; }

    /* ── Modals ───────────────────────────────────────────────────────── */
    .modal {
        width: 64;
        border: round #e89a6b;
        background: #080808;
        padding: 1 2;
        color: #eeeeee;
    }
    .modal-error { border: round #ff6b6b; }
    #modal-message { color: #eeeeee; }
    .modal-buttons { height: 3; align-horizontal: center; margin-top: 1; }
    #confirm-yes { background: #ff6b6b; color: #080808; }
    #confirm-no, #submit { background: #e89a6b; color: #080808; }
    #cancel { background: #1a1a1a; color: #eeeeee; }

    /* ── Safety banner ────────────────────────────────────────────────── */
    #real-banner { background: #ff6b6b; color: #080808; text-style: bold; padding: 0 1; }
    """

    BINDINGS = [
        Binding("c", "create", "Create"),
        Binding("s", "stop", "Stop"),
        Binding("t", "start", "Start"),
        Binding("d", "delete", "Delete"),
        Binding("g", "tag", "Tag"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "launch_ls", "Launch LocalStack"),
        Binding("x", "stop_ls", "Stop LocalStack"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Textual 1.0.0 does not honor the THEME class attribute by itself;
        # apply it explicitly so the runtime theme is actually catppuccin-mocha.
        self.theme = self.THEME
        self.items: list[dict] = []
        self._ls_on = False
        self._last_known_up: float | None = None
        self._long_op = False
        self._pending_tag_item: dict | None = None
        self._awaiting_confirm: _Waiter | None = None

    # ── Layout ──────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        if REAL:
            yield Static(
                "!!! REAL AWS MODE — actions hit your REAL AWS account !!!",
                id="real-banner",
            )
        with Horizontal(id="main-row"):
            with Vertical(id="side-left"):
                yield Static("ArcOps", id="brand")
                yield Static("Natural language → AWS", id="subtitle")
                yield Static("", id="ls-badge")
                yield Static(self._model_info(), id="model-info")
                yield Static("TOOLS", classes="panel-heading")
                yield Static("EC2 · RDS · Billing", classes="muted")
                yield Static("BINDINGS", classes="panel-heading")
                yield Static(
                    "c create · s stop · t start\n"
                    "d delete · g tag · r refresh\n"
                    "l launch ls · x stop ls · q quit",
                    classes="muted",
                )
            yield DataTable(cursor_type="row", zebra_stripes=True, id="resources")
            with Vertical(id="side-right"):
                yield Static("SEARCH", id="search-title")
                yield Input(placeholder="Describe a resource...", id="search-input")
                yield Static("", id="last-result")
                yield Static("QUICK ACTIONS", classes="panel-heading")
                yield ListView(
                    ListItem(Label("Create resource"), id="qa-create"),
                    ListItem(Label("Refresh list"), id="qa-refresh"),
                    ListItem(Label("Launch LocalStack"), id="qa-launch"),
                    ListItem(Label("Stop LocalStack"), id="qa-stop-ls"),
                    ListItem(Label("Quit"), id="qa-quit"),
                    id="quick-actions",
                )
        yield Static("", id="status")
        yield ProgressBar(id="progress", show_percentage=False)

    def on_mount(self) -> None:
        self.query_one("#status", Static).set_classes("status-neutral")
        table = self.query_one("#resources", DataTable)
        table.add_columns("#", "Type", "ID", "Info", "Tags")
        # Quick actions are visual hints only — keep them out of the focus
        # cycle so they never steal keys from the resource table.
        self.query_one("#quick-actions", ListView).can_focus = False
        self._refresh()
        self.set_interval(5.0, self._interval_refresh)
        table.focus()

    def on_resize(self, event: Any) -> None:
        """Adapt the layout to the terminal width (responsive, no @media in 1.0)."""
        try:
            main = self.query_one("#main-row")
        except NoMatches:
            return
        width = event.size.width if event.size else self.size.width
        if width <= 70:
            main.set_classes("responsive-stack responsive-compact")
        elif width <= 110:
            main.set_classes("responsive-stack")
        else:
            main.set_classes("")

    def on_key(self, event: Any) -> None:
        """Escape: cancel a pending confirmation, or leave the search input."""
        if event.key != "escape":
            return
        if self._awaiting_confirm is not None:
            waiter = self._awaiting_confirm
            if not waiter.resolved:
                waiter.ok = False
                waiter.resolved = True
                waiter.event.set()
            self._focus_resources()
            event.stop()
            return
        try:
            focused_is_input = self.focused is self.query_one("#search-input", Input)
        except NoMatches:
            return
        if focused_is_input:
            self._focus_resources()
            event.stop()

    @staticmethod
    def _model_info() -> str:
        """Model line for the left panel — env/presentational only."""
        key = os.environ.get("ARC_OPS_MODEL", "7b")
        adapter = os.environ.get("ARC_OPS_ADAPTER", "CodeSantiago/arcops")
        return f"Model: {key} (Qwen2.5)\nAdapter: {adapter}"

    def _focus_resources(self) -> None:
        """Return keyboard focus to the resource table (safe when unmounted)."""
        try:
            self.query_one("#resources", DataTable).focus()
        except NoMatches:
            pass

    # ── Status bar + search-panel result ────────────────────────────────
    def _set_status(self, text: str, kind: str = "neutral") -> None:
        try:
            status = self.query_one("#status", Static)
        except NoMatches:
            # Base screen is unmounted while a modal is on top — skip the
            # update; the next refresh or modal close will re-render.
            return
        status.update(text)
        status.set_classes(f"status-{kind}")

    def _log_result(self, text: str, kind: str = "neutral") -> None:
        """Persist the last outcome into the right search panel."""
        color = {
            "ok": C_OK,
            "warn": C_ACCENT,
            "error": C_ERROR,
            "busy": C_ACCENT,
            "neutral": C_TEXT,
        }.get(kind, C_TEXT)
        try:
            self.query_one("#last-result", Static).update(
                f"[{color}]{escape(text)}[/]"
            )
        except NoMatches:
            pass

    def _update_ls_status(self, ls_on: bool, uptime: int | None = None) -> None:
        if ls_on:
            up = uptime if uptime is not None else _ls_uptime()
            up = up if up is not None else 0
            pretty = _fmt_duration(up)
            badge = f"[{C_OK}]●[/] RUNNING ({pretty} uptime)"
            kind, msg = "ok", f"LocalStack: RUNNING ({pretty} uptime)"
        elif self._last_known_up is not None and time.time() - self._last_known_up < 5:
            badge = f"[{C_ACCENT}]●[/] RECENTLY STOPPED"
            kind, msg = "warn", "LocalStack: RECENTLY STOPPED"
        else:
            badge = f"[{C_ERROR}]●[/] STOPPED — press [l] to launch"
            kind, msg = "error", "LocalStack: STOPPED — press [l] to launch"
        self._set_status(msg, kind=kind)
        try:
            self.query_one("#ls-badge", Static).update(badge)
        except NoMatches:
            pass

    # ── Refresh ─────────────────────────────────────────────────────────
    def _interval_refresh(self) -> None:
        if not self._long_op:
            self._refresh()

    def _refresh(self) -> None:
        if self._long_op:
            return
        self._refresh_worker()

    @work(thread=True, exclusive=True)
    def _refresh_worker(self) -> None:
        ls_on = ls_check()
        uptime = _ls_uptime() if ls_on else None
        items = get_all() if (ls_on or REAL) else []
        self.call_from_thread(self._render, ls_on, items, uptime)

    def _render(self, ls_on: bool, items: list[dict], uptime: int | None = None) -> None:
        self._ls_on = ls_on
        if ls_on:
            self._last_known_up = time.time()
        try:
            table = self.query_one("#resources", DataTable)
        except NoMatches:
            # Base screen is unmounted while a modal is on top — skip the UI
            # update; the next refresh or modal close will re-render.
            return
        previous = table.cursor_row
        table.clear()
        self.items = items
        for i, item in enumerate(items, 1):
            type_cell = Text(
                item["t"],
                style=f"bold {C_OK if item['t'] == 'EC2' else C_ACCENT}",
            )
            table.add_row(str(i), type_cell, item["id"], item["info"], item["tags"])
        if items:
            target = previous if previous is not None and previous < len(items) else 0
            table.move_cursor(row=target)
        self._update_ls_status(ls_on, uptime=uptime)
        note = f"Refreshed — {len(items)} resource(s)"
        if not ls_on and not REAL:
            note += " (LocalStack stopped)"
        self._log_result(note, kind="neutral")

    def _selected_item(self) -> dict | None:
        try:
            table = self.query_one("#resources", DataTable)
        except NoMatches:
            # Base screen is unmounted while a modal is on top.
            return None
        row = table.cursor_row
        if row is None:
            return None
        try:
            return self.items[row]
        except IndexError:
            return None

    # ── Inline confirmation (no modal) ──────────────────────────────────
    def _confirm_from_thread(self, message: str) -> bool:
        """Blocking confirmation used as core's ``confirm_callable``.

        Instead of a modal screen, the question appears in the search panel
        and the user answers with ``y``/``n`` in the input — in place.
        """
        waiter = _Waiter()
        self._awaiting_confirm = waiter
        destructive = "TERMINATE" in message or "DELETE" in message or "REAL AWS" in message
        kind = "error" if destructive else "warn"

        def ask() -> None:
            self._log_result(f"Confirm: {message}  (y/n)", kind=kind)
            try:
                inp = self.query_one("#search-input", Input)
            except NoMatches:
                return
            inp.value = ""
            inp.placeholder = "y / n — confirm"
            inp.focus()

        self.call_from_thread(ask)
        waiter.event.wait(timeout=180)
        self._awaiting_confirm = None
        return waiter.ok

    # ── Long-operation coordination ─────────────────────────────────────
    def _start_long_op(self) -> None:
        self._long_op = True
        try:
            self.query_one("#progress", ProgressBar).display = True
        except NoMatches:
            pass

    def _finish_op(self) -> None:
        self._long_op = False
        try:
            self.query_one("#progress", ProgressBar).display = False
        except NoMatches:
            pass
        self._refresh()

    # ── Actions ─────────────────────────────────────────────────────────
    def action_refresh(self) -> None:
        if not self._long_op:
            self._refresh()

    def action_create(self) -> None:
        if self._long_op:
            return
        if not self._ls_on and not REAL:
            self.notify(
                "LocalStack is not running. Press [l] to launch.",
                severity="warning",
                timeout=6,
            )
            return
        # No modal: focus the search-panel input so the prompt is typed in place.
        self.query_one("#search-input", Input).focus()

    def _on_prompt(self, prompt: str | None) -> None:
        if not prompt:
            return
        self._start_long_op()
        self._set_status("Loading model (first time ~30s)...", kind="busy")
        self._log_result("Loading model (first time ~30s)...", kind="busy")
        self._create_worker(prompt)

    @on(Input.Submitted, "#search-input")
    def _on_search_submit(self, event: Input.Submitted) -> None:
        """Enter in the search panel: answers a pending confirmation, or runs create."""
        value = (event.value or "").strip().lower()
        event.input.value = ""
        if self._awaiting_confirm is not None:
            waiter = self._awaiting_confirm
            if not waiter.resolved:
                waiter.ok = value in ("y", "yes")
                waiter.resolved = True
                waiter.event.set()
            self._focus_resources()
            return
        prompt = value
        self._focus_resources()
        if not prompt:
            return
        if self._long_op:
            self.notify(
                "Busy — wait for the current operation to finish.",
                severity="warning",
                timeout=5,
            )
            return
        if not self._ls_on and not REAL:
            self.notify(
                "LocalStack is not running. Press [l] to launch.",
                severity="warning",
                timeout=6,
            )
            return
        self._start_long_op()
        self._set_status("Loading model (first time ~30s)...", kind="busy")
        self._log_result("Loading model (first time ~30s)...", kind="busy")
        self._create_worker(prompt)

    @work(thread=True, exclusive=True)
    def _create_worker(self, prompt: str) -> None:
        try:
            with _suppress_core_printing():
                status, msg = create(
                    prompt, confirm_callable=self._confirm_from_thread
                )
        except Exception as exc:  # pragma: no cover - unexpected engine failure
            status, msg = "error", str(exc)
        severity = {
            "ok": "information",
            "blocked": "warning",
            "cancelled": "warning",
            "error": "error",
        }.get(status, "information")
        kind = "ok" if status == "ok" else ("error" if status == "error" else "warn")
        self.call_from_thread(
            self.notify, f"[{status}] {msg}", severity=severity, timeout=10
        )
        self.call_from_thread(self._log_result, f"[{status}] {msg}", kind=kind)
        self.call_from_thread(self._finish_op)

    def action_stop(self) -> None:
        self._act_on_selected("stop-instances", "Stopped")

    def action_start(self) -> None:
        self._act_on_selected("start-instances", "Started")

    def action_delete(self) -> None:
        self._act_on_selected(None, "Deleted")

    def _act_on_selected(self, cmd: str | None, label: str) -> None:
        if self._long_op:
            return
        item = self._selected_item()
        if item is None:
            self.notify(
                "Select a resource row first (up/down arrows, then s/t/d/g).",
                severity="warning",
                timeout=6,
            )
            return
        if cmd is None:
            cmd = "terminate-instances" if item["t"] == "EC2" else "delete-db-instance"
        self._action_worker(item, cmd, label)

    @work(thread=True, exclusive=True)
    def _action_worker(self, item: dict, cmd: str, label: str) -> None:
        self.call_from_thread(self._start_long_op)
        confirmed = {"ok": True}

        def confirm(message: str) -> bool:
            ok = self._confirm_from_thread(message)
            confirmed["ok"] = ok
            return ok

        try:
            with _suppress_core_printing():
                act(item, cmd, confirm_callable=confirm)
        except Exception as exc:  # pragma: no cover - unexpected engine failure
            self.call_from_thread(
                self.notify, f"[error] {exc}", severity="error", timeout=8
            )
            self.call_from_thread(self._log_result, f"[error] {exc}", kind="error")
            self.call_from_thread(self._finish_op)
            return
        if confirmed["ok"]:
            self.call_from_thread(
                self.notify, f"{label} {item['id']}", severity="information", timeout=5
            )
            self.call_from_thread(
                self._log_result, f"{label} {item['id']}", kind="ok"
            )
        else:
            self.call_from_thread(
                self.notify,
                f"Cancelled: {item['id']}",
                severity="warning",
                timeout=5,
            )
            self.call_from_thread(
                self._log_result, f"Cancelled: {item['id']}", kind="warn"
            )
        self.call_from_thread(self._finish_op)

    def action_tag(self) -> None:
        if self._long_op:
            return
        item = self._selected_item()
        if item is None:
            self.notify(
                "Select a resource row first (up/down arrows, then g).",
                severity="warning",
                timeout=6,
            )
            return
        self._pending_tag_item = item
        self.push_screen(
            InputScreen(
                label="Tag value (sets Name=<value>):",
                placeholder="e.g. webserver",
                submit_label="Tag",
            ),
            self._on_tag_value,
        )

    def _on_tag_value(self, value: str | None) -> None:
        item = self._pending_tag_item
        self._pending_tag_item = None
        if not value or item is None:
            return
        self._tag_worker(item, value)

    @work(thread=True, exclusive=True)
    def _tag_worker(self, item: dict, value: str) -> None:
        self.call_from_thread(self._start_long_op)
        try:
            tag_it(item, "Name", value)
        except Exception as exc:  # pragma: no cover - unexpected engine failure
            self.call_from_thread(
                self.notify, f"[error] {exc}", severity="error", timeout=8
            )
            self.call_from_thread(self._log_result, f"[error] {exc}", kind="error")
            self.call_from_thread(self._finish_op)
            return
        self.call_from_thread(
            self.notify,
            f"Tagged {item['id']} as Name={value}",
            severity="information",
            timeout=5,
        )
        self.call_from_thread(
            self._log_result, f"Tagged {item['id']} as Name={value}", kind="ok"
        )
        self.call_from_thread(self._finish_op)

    def action_launch_ls(self) -> None:
        if self._long_op:
            return
        if self._ls_on:
            self._ls_diag_worker()
            return
        self._start_long_op()
        self._set_status("Starting LocalStack...", kind="busy")
        self._log_result("Starting LocalStack...", kind="busy")
        self._launch_worker()

    @work(thread=True)
    def _ls_diag_worker(self) -> None:
        """Container status + health probe when LocalStack is already up."""
        try:
            r = subprocess.run(
                ["docker", "ps", "--filter", "name=localstack", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            h = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "http://localhost:4566/_localstack/health"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            msg = (
                f"LocalStack container: {r.stdout.strip() or 'not found'} | "
                f"Health: {h.stdout.strip() or 'no response'}"
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            msg = f"Diagnostics failed: {exc}"
        self.call_from_thread(self.notify, msg, severity="information", timeout=8)
        self.call_from_thread(self._log_result, msg, kind="neutral")

    @work(thread=True, exclusive=True)
    def _launch_worker(self) -> None:
        global LS_START_TIME
        try:
            r = subprocess.run(
                ["docker", "start", "localstack"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0:
                run_cmd = [
                    "docker", "run", "-d", "--name", "localstack",
                    "-p", "4566:4566", "localstack/localstack",
                ]
                ls_token = os.environ.get("LOCALSTACK_AUTH_TOKEN")
                if ls_token:
                    run_cmd[3:3] = ["-e", f"LOCALSTACK_AUTH_TOKEN={ls_token}"]
                r = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                err = (r.stderr or "").strip()[:200] or "docker command failed"
                self.call_from_thread(
                    self.notify,
                    f"Failed to start LocalStack: {err}",
                    severity="error",
                    timeout=8,
                )
                self.call_from_thread(
                    self._log_result, f"Failed to start LocalStack: {err}", kind="error"
                )
                self.call_from_thread(self._finish_op)
                return
            spin = ["[•]", "[•>]", "[•>•]", "[>•>]"]
            for i in range(40):
                self.call_from_thread(
                    self._set_status, f"Booting LocalStack... {spin[i % 4]}", kind="busy"
                )
                time.sleep(1)
                if ls_check():
                    LS_START_TIME = time.time()
                    break
            self.call_from_thread(
                self.notify, "LocalStack started!", severity="information", timeout=5
            )
            self.call_from_thread(self._log_result, "LocalStack started", kind="ok")
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.call_from_thread(
                self.notify,
                f"Failed to start LocalStack: {exc}",
                severity="error",
                timeout=8,
            )
            self.call_from_thread(
                self._log_result, f"Failed to start LocalStack: {exc}", kind="error"
            )
        finally:
            self.call_from_thread(self._finish_op)

    def action_stop_ls(self) -> None:
        if self._long_op:
            return
        if not self._ls_on:
            self.notify(
                "LocalStack is not running.", severity="warning", timeout=5
            )
            return
        self._start_long_op()
        self._set_status("Stopping LocalStack...", kind="busy")
        self._log_result("Stopping LocalStack...", kind="busy")
        self._stop_worker()

    @work(thread=True, exclusive=True)
    def _stop_worker(self) -> None:
        try:
            r = subprocess.run(
                ["docker", "stop", "localstack"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                self.call_from_thread(
                    self.notify,
                    "LocalStack stopped.",
                    severity="information",
                    timeout=5,
                )
                self.call_from_thread(self._log_result, "LocalStack stopped", kind="ok")
            else:
                err = (r.stderr or "").strip()[:200] or "docker stop failed"
                self.call_from_thread(
                    self.notify, f"Failed to stop LocalStack: {err}", severity="error", timeout=8
                )
                self.call_from_thread(
                    self._log_result, f"Failed to stop LocalStack: {err}", kind="error"
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.call_from_thread(
                self.notify,
                f"Failed to stop LocalStack: {exc}",
                severity="error",
                timeout=8,
            )
            self.call_from_thread(
                self._log_result, f"Failed to stop LocalStack: {exc}", kind="error"
            )
        finally:
            self.call_from_thread(self._finish_op)

    # ── Search-panel quick actions ──────────────────────────────────────
    @on(ListView.Selected, "#quick-actions")
    def _on_quick_action(self, event: ListView.Selected) -> None:
        action = {
            "qa-create": self.action_create,
            "qa-refresh": self.action_refresh,
            "qa-launch": self.action_launch_ls,
            "qa-stop-ls": self.action_stop_ls,
            "qa-quit": self.action_quit,
        }.get(event.item.id)
        if action is not None:
            action()


def main() -> None:
    """Entry point used by ``arcops tui`` and ``python -m app.tui``."""
    _configure_stdio()
    ArcOpsApp().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Bye!")
