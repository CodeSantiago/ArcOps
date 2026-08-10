#!/usr/bin/env python3
"""ArcOps TUI — Textual dashboard. Run: python -m app.tui (or arcops tui).

Pure presentation layer: renders the dashboard and delegates every AWS
call and all inference to the shared engine (``cloudops_fc.core``). No AWS
or model logic lives here — the engine stays the single source of truth.

Blocking work (resource listing, model inference, LocalStack boot) runs in
Textual workers so the interface never freezes. Targets LocalStack by
default; real AWS mode is opt-in via ``ARC_OPS_REAL=1`` and every
destructive action requires an explicit on-screen confirmation before the
AWS CLI runs.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.dom import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

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

LS_START_TIME: float | None = None  # When LocalStack was started


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


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No question used for destructive actions and approvals."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message
        self._waiter: _Waiter | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="modal"):
            yield Label(self._message, id="modal-message")
            with Horizontal(classes="modal-buttons"):
                yield Button("Yes", id="confirm-yes", variant="error")
                yield Button("No", id="confirm-no", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#confirm-no", Button).focus()

    def on_unmount(self) -> None:
        # Never leave a worker thread waiting, even if the screen is popped.
        if self._waiter is not None and not self._waiter.resolved:
            self._waiter.resolved = True
            self._waiter.event.set()

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        ok = event.button.id == "confirm-yes"
        if self._waiter is not None:
            self._waiter.ok = ok
            self._waiter.resolved = True
            self._waiter.event.set()
        self.dismiss(ok)


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
    """ArcOps terminal dashboard."""

    TITLE = "ArcOps Dashboard"
    SUBTITLE = "Natural language -> AWS"
    THEME = "catppuccin-mocha"

    CSS = """
    DataTable { border: round $primary; }
    #resources { height: 1fr; }
    #status { padding: 0 2; text-style: bold; background: $surface; margin-bottom: 1; }
    #real-banner { background: red; color: white; text-style: bold; padding: 0 1; }
    .status-ok { color: $success; }
    .status-warn { color: $warning; }
    .status-error { color: $error; }
    .status-busy { color: $accent; }
    .status-neutral { color: $text; }
    .modal {
        width: 64;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    .modal-buttons { height: 3; align-horizontal: center; margin-top: 1; }
    """

    BINDINGS = [
        Binding("c", "create", "Create"),
        Binding("s", "stop", "Stop"),
        Binding("t", "start", "Start"),
        Binding("d", "delete", "Delete"),
        Binding("g", "tag", "Tag"),
        Binding("r", "refresh", "Refresh"),
        Binding("l", "launch_ls", "Launch LocalStack"),
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

    # ── Layout ──────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        if REAL:
            yield Static(
                "!!! REAL AWS MODE — actions hit your REAL AWS account !!!",
                id="real-banner",
            )
        yield Static("", id="status")
        yield DataTable(cursor_type="row", zebra_stripes=True, id="resources")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#status", Static).set_classes("status-neutral")
        table = self.query_one("#resources", DataTable)
        table.add_columns("#", "Type", "ID", "Info", "Tags")
        self._refresh()
        self.set_interval(5.0, self._interval_refresh)
        table.focus()

    # ── Status bar ──────────────────────────────────────────────────────
    def _set_status(self, text: str, kind: str = "neutral") -> None:
        try:
            status = self.query_one("#status", Static)
        except NoMatches:
            # Base screen is unmounted while a modal is on top — skip the
            # update; the next refresh or modal close will re-render.
            return
        status.update(text)
        status.set_classes(f"status-{kind}")

    def _update_ls_status(self, ls_on: bool) -> None:
        if ls_on:
            up = int(time.time() - LS_START_TIME) if LS_START_TIME else 0
            self._set_status(f"LocalStack: RUNNING ({up}s uptime)", kind="ok")
        elif self._last_known_up is not None and time.time() - self._last_known_up < 5:
            self._set_status("LocalStack: RECENTLY STOPPED", kind="warn")
        else:
            self._set_status("LocalStack: STOPPED — press [l] to launch", kind="error")

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
        items = get_all() if (ls_on or REAL) else []
        self.call_from_thread(self._render, ls_on, items)

    def _render(self, ls_on: bool, items: list[dict]) -> None:
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
            table.add_row(str(i), item["t"], item["id"], item["info"], item["tags"])
        if items:
            target = previous if previous is not None and previous < len(items) else 0
            table.move_cursor(row=target)
        self._update_ls_status(ls_on)

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

    # ── Threaded confirmation bridge ────────────────────────────────────
    def _confirm_from_thread(self, message: str) -> bool:
        """Blocking confirmation used as core's ``confirm_callable``.

        Runs on a worker thread; asks the user through the UI and waits.
        The engine decides which actions need confirmation.
        """
        waiter = _Waiter()

        def ask() -> None:
            screen = ConfirmScreen(message)
            screen._waiter = waiter
            self.push_screen(screen)

        self.call_from_thread(ask)
        waiter.event.wait(timeout=180)
        return waiter.ok

    # ── Long-operation coordination ─────────────────────────────────────
    def _start_long_op(self) -> None:
        self._long_op = True

    def _finish_op(self) -> None:
        self._long_op = False
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
        self.push_screen(
            InputScreen(
                label="Describe the resource to create (natural language):",
                placeholder='e.g. "Create a t3.micro server"',
                submit_label="Run",
            ),
            self._on_prompt,
        )

    def _on_prompt(self, prompt: str | None) -> None:
        if not prompt:
            return
        self._start_long_op()
        self._set_status("Loading model (first time ~30s)...", kind="busy")
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
        self.call_from_thread(
            self.notify, f"[{status}] {msg}", severity=severity, timeout=10
        )
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
            self.call_from_thread(self._finish_op)
            return
        if confirmed["ok"]:
            self.call_from_thread(
                self.notify, f"{label} {item['id']}", severity="information", timeout=5
            )
        else:
            self.call_from_thread(
                self.notify,
                f"Cancelled: {item['id']}",
                severity="warning",
                timeout=5,
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
            self.call_from_thread(self._finish_op)
            return
        self.call_from_thread(
            self.notify,
            f"Tagged {item['id']} as Name={value}",
            severity="information",
            timeout=5,
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
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.call_from_thread(
                self.notify,
                f"Failed to start LocalStack: {exc}",
                severity="error",
                timeout=8,
            )
        finally:
            self.call_from_thread(self._finish_op)


def main() -> None:
    """Entry point used by ``arcops tui`` and ``python -m app.tui``."""
    _configure_stdio()
    ArcOpsApp().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Bye!")
