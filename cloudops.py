#!/usr/bin/env python3
"""
ArcOps — Natural language → AWS JSON tool calls.

Usage:
    arcops "create a t3.micro server"       # Quick prompt (auto-starts server)
    arcops start                            # Start everything + TUI
    arcops stop                             # Stop everything
    arcops serve                            # Start persistent server only
    arcops dashboard                        # Open web UI in browser
    arcops tools                            # List available tools
    arcops --json "create a server"          # JSON-only output (for piping)
    arcops --help                           # This help
"""
import json, os, sys, socket, threading, time, signal, subprocess
from pathlib import Path

CACHE_FILE = Path.home() / ".arcops" / "server.port"
PID_FILE = Path.home() / ".arcops" / "server.pid"


# ── Available tools (for `arcops tools`) ──────────────────────────────────
TOOLS = {
    "create_ec2_instance": {
        "description": "Create an EC2 virtual server",
        "params": "region (required), instance_type (required), ami_id, security_group_rules, tags, key_name, subnet_id, associate_public_ip",
        "example": "Create a t3.micro server in us-east-1 with port 443 open"
    },
    "restart_database": {
        "description": "Restart an RDS database instance",
        "params": "db_instance_identifier (required), region (required), force_failover",
        "example": "Restart the production database in us-west-2 with failover"
    },
    "get_billing_alert": {
        "description": "Retrieve AWS cost and usage data",
        "params": "time_period_start, time_period_end, granularity (DAILY/MONTHLY/HOURLY), metrics, group_by_service",
        "example": "How much did we spend this month on AWS?"
    }
}


# ── Server management ─────────────────────────────────────────────────────

def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server_proc(port):
    """Start the model server as a BACKGROUND process (not a thread)."""
    project = Path(__file__).resolve().parent
    proc = subprocess.Popen(
        ["uv", "run", "python", "-c", f"""
import sys; sys.path.insert(0, r'{project}')
from scripts.mcp_server import load_model, generate_tool_call
import json, socket, threading

load_model()

s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", {port}))
s.listen(5)
print("READY", flush=True)

while True:
    conn, _ = s.accept()
    try:
        data = conn.recv(65536).decode()
        req = json.loads(data)
        result = generate_tool_call(req["prompt"])
        conn.send(json.dumps(result).encode())
    except:
        pass
    finally:
        conn.close()
"""],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=project, start_new_session=True
    )
    # Wait for READY
    import time as _time
    for _ in range(60):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(str(port))
            PID_FILE.write_text(str(proc.pid))
            return port
        except:
            s.close()
            _time.sleep(2)
    raise RuntimeError("Server failed to start")


def get_server_port():
    if CACHE_FILE.exists():
        port = int(CACHE_FILE.read_text().strip())
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return port
        except:
            pass
    return None


def stop_server():
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print("Stop ArcOps server stopped")
        except:
            pass
        PID_FILE.unlink(missing_ok=True)
    if CACHE_FILE.exists():
        CACHE_FILE.unlink(missing_ok=True)


def call_server(prompt, port):
    s = socket.create_connection(("127.0.0.1", port), timeout=120)
    s.send(json.dumps({"prompt": prompt}).encode())
    data = s.recv(65536)
    s.close()
    return json.loads(data.decode())


def ensure_server():
    """Return port of running server, starting one if needed."""
    port = get_server_port()
    if port is not None:
        return port
    print("*  Starting ArcOps server (first load ~30s)...")
    port = find_free_port()
    threading.Thread(target=lambda: start_server_proc(port), daemon=True).start()
    # Wait for it
    for _ in range(60):
        _port = get_server_port()
        if _port:
            return _port
        time.sleep(2)
    print("X Failed to start ArcOps server")
    sys.exit(1)


# ── Main CLI ──────────────────────────────────────────────────────────────

def start_everything():
    """Start LocalStack + ArcOps server + open TUI. One command."""
    from pathlib import Path
    project = Path(__file__).resolve().parent
    
    print("* Starting LocalStack...")
    # Kill old container, start new with persistence
    subprocess.run(["docker", "rm", "-f", "localstack"], capture_output=True)
    ls_proc = subprocess.Popen(
        ["docker", "run", "-d", "--name", "localstack",
         "-p", "4566:4566",
         "-v", "localstack_data:/var/lib/localstack",
         "-e", "LOCALSTACK_AUTH_TOKEN=ls-DIBaXisO-gUza-9468-YeQA-wUCo19799a1f",
         "localstack/localstack"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    ls_proc.wait()
    import time as _time
    _time.sleep(8)  # wait for LocalStack to be ready
    
    print("* Starting ArcOps model server...")
    port = find_free_port()
    threading.Thread(target=lambda: start_server_proc(port), daemon=True).start()
    for _ in range(60):
        p = get_server_port()
        if p:
            print(f"* ArcOps ready")
            break
        _time.sleep(2)
    
    print("* Opening TUI dashboard...")
    tui = project / "app" / "tui.py"
    subprocess.Popen(
        ["cmd.exe", "/c", "start", "ArcOps", "wt",
         "--title", "ArcOps TUI",
         "--tabColor", "#58a6ff",
         "uv", "run", "python", str(tui)],
        cwd=project
    )
    print("\n  Everything is running!")
    print("  TUI: open (new terminal window)")
    print("  CLI: arcops \"your prompt\"")
    print("  API: http://localhost:8080")
    print("  To stop everything: arcops stop\n")


def stop_everything():
    """Stop ArcOps server + LocalStack."""
    stop_server()
    subprocess.run(["docker", "rm", "-f", "localstack"], capture_output=True)
    print("* LocalStack stopped")
    print("* ArcOps server stopped")
    print("\n  > ArcOps — Available AWS Tools\n")
    for name, info in TOOLS.items():
        print(f"  {name}")
        print(f"     {info['description']}")
        print(f"     Params: {info['params']}")
        print(f"     Try:    arcops \"{info['example']}\"\n")


def show_help():
    print("""
  > ArcOps — Natural Language → AWS JSON Tool Calls

  USAGE
    arcops "your prompt"          → Generate a JSON tool call
    arcops exec "your prompt"     → Show equivalent AWS CLI command
    arcops --json "your prompt"   → Raw JSON output (for piping)
    arcops start                  → Start everything + TUI dashboard
    arcops stop                   → Stop everything (model + LocalStack)
    arcops serve                  → Start model server only (background)
    arcops tools                  → List all available AWS tools

  EXAMPLES
    arcops "Create a t3.micro server in us-east-1 with port 80"
    arcops "Restart the production database in us-west-2"
    arcops "How much did we spend this month on AWS?"
    arcops --json "Create a server with tags Name=web" | python3 -m json.tool
    arcops exec "Create a t3.micro EC2 server"
    arcops exec --live "Create a t3.micro EC2 server"  # needs LocalStack

  NOTES
    • First call loads the model (~30s). Subsequent calls are instant.
    • The server stays alive in background. Use `arcops stop` to kill it.
    • No data leaves your machine. Runs 100% locally.
    • Works in English and Spanish.
""")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        show_help()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "start":
        start_everything()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop_everything()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "tools":
        show_tools()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop_server()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        port = ensure_server()
        print(f"*  ArcOps server ready on port {port}")
        print(f"   Use: arcops \"your prompt\"")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            stop_server()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "dashboard":
        """Open ArcOps TUI in a new terminal window."""
        project = Path(__file__).resolve().parent
        tui_script = str(project / "app" / "tui.py")
        
        # Try Windows Terminal first, fallback to wt, then gnome-terminal
        cmd = ["cmd.exe", "/c", "start", "ArcOps", "wt",
               "--title", "ArcOps TUI",
               "--tabColor", "#58a6ff",
               "uv", "run", "python", tui_script]
        try:
            subprocess.Popen(cmd, cwd=project)
            print("*  ArcOps Dashboard opened in new terminal window")
        except FileNotFoundError:
            # Fallback: gnome-terminal
            try:
                subprocess.Popen(["gnome-terminal", "--", "uv", "run", "python", tui_script], cwd=project)
                print("*  ArcOps Dashboard opened in new terminal window")
            except FileNotFoundError:
                print("Warning  Could not open new terminal. Run manually:")
                print(f"   uv run python {tui_script}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "exec":
        from app.exec import main as exec_main
        sys.argv = sys.argv[1:]  # Remove 'exec' from args
        exec_main()
        return

    # Default: prompt mode
    if len(sys.argv) < 2:
        show_help()
        return

    # Strip flags from prompt
    flags = {"--json"}
    prompt_parts = [a for a in sys.argv[1:] if a not in flags]
    prompt = " ".join(prompt_parts)

    try:
        port = ensure_server()
        result = call_server(prompt, port)
    except Exception as e:
        print(f"X Error: {e}")
        sys.exit(1)

    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False))
    else:
        # Always run safety check
        from app.safety import check as safety_check
        tool_name = result.get("name", "")
        arguments = result.get("arguments", {})
        sr = safety_check(tool_name, arguments)
        print(f"\n  > {prompt}")
        print(f"  => {json.dumps(result, ensure_ascii=False)}")
        if sr.warnings or sr.errors:
            print(f"\n  -- Safety --")
            if sr.warnings:
                for w in sr.warnings:
                    print(f"  {w}")
            if sr.errors:
                for e in sr.errors:
                    print(f"  Error: {e}")
            if sr.blocked:
                print(f"  Action BLOCKED")
            elif sr.requires_approval:
                print(f"  Requires approval")


if __name__ == "__main__":
    main()
