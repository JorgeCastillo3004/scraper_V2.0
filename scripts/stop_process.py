#!/usr/bin/env python3
"""
stop_process.py
───────────────
Monitor interactivo de procesos para el scraper.

Detecta y permite eliminar:
  - Drivers / browsers huérfanos (geckodriver, chromedriver)
  - Browsers con CPU o RAM excesiva (Firefox tabs runaway, Chrome)
  - Procesos zombie
  - Instancias colgadas del scraper (main2.py, paralel_execution.py…)

Uso:
    python scripts/stop_process.py            # modo interactivo completo
    python scripts/stop_process.py --show     # solo mostrar, sin matar
    python scripts/stop_process.py --auto     # mata problemáticos sin preguntar
    python scripts/stop_process.py --top 15   # top 15 procesos por CPU y RAM
    python scripts/stop_process.py --pid 1234 # matar PID específico
    python scripts/stop_process.py --test     # tests de verificación
"""

import argparse
import os
import socket
import sys
import time

import psutil
from rich.columns import Columns
from rich.console import Console
from rich import box
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

console = Console()

# ── Umbrales ───────────────────────────────────────────────────────────────────

CPU_BROWSER_PCT  = 50.0   # % CPU para marcar un browser como "pesado"
RAM_BROWSER_MB   = 600    # MB RAM para marcar un browser como "pesado"
CPU_SCRAPER_PCT  = 60.0   # % CPU para marcar un proceso del scraper como "pesado"
RAM_SCRAPER_MB   = 400    # MB RAM para marcar un proceso del scraper como "pesado"
CPU_TOP_PCT      = 30.0   # umbral mínimo para aparecer en --top

# ── Keywords ───────────────────────────────────────────────────────────────────

DRIVER_KEYWORDS  = ["geckodriver", "chromedriver"]
BROWSER_KEYWORDS = ["firefox", "firefox-bin", "chrome", "chromium"]
SCRAPER_KEYWORDS = ["main2.py", "paralel_execution.py", "paralel_players.py",
                    "milestone", "test_server.py"]
SELENIUM_MARKERS = ["marionette", "--marionette", "remote-debugging-port",
                    "disable-features=WebAssemblyTrapHandler"]
JUPYTER_MARKERS  = ["nbserver", "jupyter", "ipykernel", "jupyter-notebook"]

# Procesos que NUNCA se tocan
SYSTEM_SAFELIST  = [
    "networkd-dispatcher", "Xorg", "gnome-shell", "gdm", "systemd",
    "dbus", "pulseaudio", "pipewire", "redis-server",
    "hidpi", "pop-transition",
]

# Procesos de Python del sistema que tampoco se tocan
PYTHON_SAFELIST  = ["uvicorn", "jupyter-notebook", "jupyter-noteboo",
                    "ipykernel_launcher"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_cmd(proc: psutil.Process) -> str:
    try:
        parts = proc.cmdline()
        return " ".join(parts) if parts else proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return proc.name()


def safe_mem_mb(proc: psutil.Process) -> float:
    try:
        return proc.memory_info().rss / 1_048_576
    except Exception:
        return 0.0


def safe_cpu(proc: psutil.Process) -> float:
    try:
        return proc.cpu_percent(interval=None)
    except Exception:
        return 0.0


def runtime_str(proc: psutil.Process) -> str:
    try:
        secs = int(time.time() - proc.create_time())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs//60}m"
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h}h{m:02d}m"
    except Exception:
        return "?"


def is_safelist(proc: psutil.Process) -> bool:
    cmd = safe_cmd(proc)
    name = proc.name() if hasattr(proc, 'name') else ''
    try:
        name = proc.name()
    except Exception:
        name = ''
    return (any(s in cmd for s in SYSTEM_SAFELIST) or
            any(s in name for s in PYTHON_SAFELIST) or
            any(s in cmd  for s in PYTHON_SAFELIST))


def is_selenium_driver(proc: psutil.Process) -> bool:
    """True si el proceso es un geckodriver/chromedriver activo."""
    cmd = safe_cmd(proc)
    return any(m in cmd for m in SELENIUM_MARKERS) or \
           any(k in proc.name().lower() for k in DRIVER_KEYWORDS)


def _port_from_geckodriver(proc: psutil.Process) -> int | None:
    """Extrae el puerto --port del cmdline de geckodriver."""
    try:
        parts = proc.cmdline()
        for i, part in enumerate(parts):
            if part == "--port" and i + 1 < len(parts):
                return int(parts[i + 1])
    except Exception:
        pass
    return None


def _python_connected_to_port(port: int) -> bool:
    """Comprueba si algún proceso Python tiene conexión establecida al puerto."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if (conn.raddr and conn.raddr.port == port and
                    conn.status == psutil.CONN_ESTABLISHED):
                try:
                    p = psutil.Process(conn.pid)
                    if "python" in p.name().lower():
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def is_geckodriver_orphan(proc: psutil.Process) -> bool:
    """
    Un geckodriver es huérfano si ningún proceso Python está conectado
    activamente a su puerto WebDriver.
    """
    port = _port_from_geckodriver(proc)
    if port is None:
        return True   # sin puerto → huérfano
    return not _python_connected_to_port(port)


def get_current_user() -> str:
    return os.environ.get("USER", "")


# ── Escaneo ────────────────────────────────────────────────────────────────────

def scan_processes() -> dict:
    """
    Categorías devueltas:
      orphan_drivers  — geckodriver sin cliente Python conectado
      heavy_browsers  — firefox/chrome con CPU > umbral O RAM > umbral
      zombies         — estado Z
      heavy_scrapers  — procesos del scraper con CPU/RAM excesiva
    """
    current_user = get_current_user()

    # Primera pasada: calentar medición CPU
    all_procs = []
    for p in psutil.process_iter(['pid', 'name', 'status', 'ppid', 'username']):
        try:
            if p.info['username'] != current_user:
                continue
            p.cpu_percent(interval=None)
            all_procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    time.sleep(0.8)  # intervalo para obtener CPU real

    result = {
        "orphan_drivers": [],
        "heavy_browsers": [],
        "zombies":        [],
        "heavy_scrapers": [],
    }

    for p in all_procs:
        try:
            name   = p.info['name'].lower()
            status = p.info['status']

            if is_safelist(p):
                continue

            # ── Zombie ──
            if status == psutil.STATUS_ZOMBIE:
                result["zombies"].append(p)
                continue

            cpu = safe_cpu(p)
            mb  = safe_mem_mb(p)

            # ── Geckodriver / Chromedriver huérfano ──
            if any(k in name for k in DRIVER_KEYWORDS):
                if is_geckodriver_orphan(p):
                    result["orphan_drivers"].append(p)
                continue  # no evaluar como browser pesado

            # ── Browser pesado (firefox-bin, chrome) ──
            if any(k in name for k in BROWSER_KEYWORDS):
                if cpu > CPU_BROWSER_PCT or mb > RAM_BROWSER_MB:
                    result["heavy_browsers"].append(p)
                continue

            # ── Scraper pesado ──
            cmd = safe_cmd(p)
            if any(k in cmd for k in SCRAPER_KEYWORDS):
                if cpu > CPU_SCRAPER_PCT or mb > RAM_SCRAPER_MB:
                    result["heavy_scrapers"].append(p)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return result


def scan_top(n: int = 15) -> list:
    """Top N procesos del usuario actual por CPU + RAM combinado."""
    current_user = get_current_user()
    procs = []

    for p in psutil.process_iter(['pid', 'name', 'username']):
        try:
            if p.info['username'] != current_user:
                continue
            p.cpu_percent(interval=None)
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    time.sleep(0.8)

    rows = []
    for p in procs:
        try:
            cpu = safe_cpu(p)
            mb  = safe_mem_mb(p)
            if cpu > 0.5 or mb > 100:
                rows.append((p, cpu, mb))
        except Exception:
            pass

    # Ordenar por CPU desc, luego RAM desc
    rows.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return rows[:n]


# ── Paneles y tablas ───────────────────────────────────────────────────────────

def mem_panel(label: str = "") -> Panel:
    vm  = psutil.virtual_memory()
    sw  = psutil.swap_memory()
    used = vm.used  / 1_073_741_824
    tot  = vm.total / 1_073_741_824
    pct  = vm.percent
    su   = sw.used  / 1_073_741_824
    sp   = sw.percent

    bar_len = 30
    filled  = int(bar_len * pct / 100)
    color   = "red" if pct > 85 else "yellow" if pct > 65 else "green"
    bar_ram = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * (bar_len - filled)}[/dim]"

    sw_filled = int(bar_len * sp / 100)
    sw_color  = "red" if sp > 70 else "yellow" if sp > 40 else "cyan"
    bar_swap  = f"[{sw_color}]{'█' * sw_filled}[/{sw_color}][dim]{'░' * (bar_len - sw_filled)}[/dim]"

    text = Text.assemble(
        ("RAM  ", "bold white"),
        Text.from_markup(bar_ram),
        f"  {used:.1f} / {tot:.1f} GB  ({pct}%)\n",
        ("Swap ", "bold white"),
        Text.from_markup(bar_swap),
        f"  {su:.1f} GB  ({sp}%)",
    )
    return Panel(text, title=f"[bold]Memoria  {label}[/bold]",
                 border_style="dim", padding=(0, 1))


def _proc_table(procs: list, title: str, color: str,
                show_cpu: bool = True) -> Table:
    t = Table(title=title, box=box.SIMPLE_HEAD, title_style=f"bold {color}")
    t.add_column("PID",    style=color, width=7)
    t.add_column("Nombre", width=20)
    if show_cpu:
        t.add_column("CPU %",  justify="right", width=7)
    t.add_column("RAM MB", justify="right", width=8)
    t.add_column("Uptime", width=8)
    t.add_column("Cmdline", style="dim", max_width=55, no_wrap=True)

    for p in sorted(procs, key=lambda x: safe_cpu(x) + safe_mem_mb(x)/10,
                    reverse=True):
        try:
            cpu = safe_cpu(p)
            mb  = safe_mem_mb(p)
            cpu_color = "red" if cpu > 70 else "yellow" if cpu > 40 else "white"
            row = [str(p.pid), p.name()[:20]]
            if show_cpu:
                row.append(f"[{cpu_color}]{cpu:.1f}[/{cpu_color}]")
            row += [f"{mb:.0f}", runtime_str(p), safe_cmd(p)[:55]]
            t.add_row(*row)
        except psutil.NoSuchProcess:
            pass
    return t


def _zombie_table(procs: list) -> Table:
    t = Table(title="Procesos Zombie", box=box.SIMPLE_HEAD,
              title_style="bold red")
    t.add_column("PID",    style="red", width=7)
    t.add_column("Nombre", width=20)
    t.add_column("PPID",   width=7)
    t.add_column("Parent", style="dim", width=22)
    for p in procs:
        try:
            try:
                parent_name = psutil.Process(p.ppid()).name()
            except Exception:
                parent_name = "? (muerto)"
            t.add_row(str(p.pid), p.name(), str(p.ppid()), parent_name)
        except psutil.NoSuchProcess:
            pass
    return t


def _top_table(rows: list) -> Table:
    t = Table(title="Top procesos por CPU + RAM", box=box.SIMPLE_HEAD,
              title_style="bold cyan")
    t.add_column("PID",    style="cyan", width=7)
    t.add_column("Nombre", width=22)
    t.add_column("CPU %",  justify="right", width=7)
    t.add_column("RAM MB", justify="right", width=8)
    t.add_column("Uptime", width=8)
    t.add_column("Cmdline", style="dim", max_width=50, no_wrap=True)
    for p, cpu, mb in rows:
        try:
            cpu_color = "red" if cpu > 70 else "yellow" if cpu > 30 else "white"
            ram_color = "red" if mb > 1000 else "yellow" if mb > 500 else "white"
            t.add_row(
                str(p.pid),
                p.name()[:22],
                f"[{cpu_color}]{cpu:.1f}[/{cpu_color}]",
                f"[{ram_color}]{mb:.0f}[/{ram_color}]",
                runtime_str(p),
                safe_cmd(p)[:50],
            )
        except psutil.NoSuchProcess:
            pass
    return t


def _summary_table(before: dict, after: dict) -> Table:
    def count(d, k): return len(d.get(k, []))

    vm_before = before.get("_vm_used_gb", 0)
    vm_after  = psutil.virtual_memory().used / 1_073_741_824

    t = Table(title="Resumen de limpieza", box=box.ROUNDED,
              title_style="bold green", border_style="green")
    t.add_column("Categoría",  style="bold", width=25)
    t.add_column("Antes",  justify="right", width=10)
    t.add_column("Después", justify="right", width=10)
    t.add_column("Δ",       justify="right", width=10)

    def row(label, b, a, unit=""):
        diff  = a - b
        sign  = "+" if diff > 0 else ""
        color = "red" if diff > 0 else "green" if diff < 0 else "dim"
        t.add_row(label,
                  f"{b:.0f}{unit}", f"{a:.0f}{unit}",
                  f"[{color}]{sign}{diff:.0f}{unit}[/{color}]")

    row("Drivers huérfanos",   count(before,"orphan_drivers"),  count(after,"orphan_drivers"))
    row("Browsers pesados",    count(before,"heavy_browsers"),   count(after,"heavy_browsers"))
    row("Zombies",             count(before,"zombies"),          count(after,"zombies"))
    row("Scrapers pesados",    count(before,"heavy_scrapers"),   count(after,"heavy_scrapers"))
    row("RAM usada",           vm_before*1024, vm_after*1024,   " MB")
    return t


# ── Kill logic ─────────────────────────────────────────────────────────────────

def execute_kills(targets: list) -> tuple[int, int]:
    killed = failed = 0
    for p in targets:
        try:
            pid  = p.pid
            name = p.name()
            p.terminate()
            try:
                p.wait(timeout=2)
            except psutil.TimeoutExpired:
                p.kill()
            console.print(f"    [red][KILL][/red] PID {pid} ({name})")
            killed += 1
        except psutil.NoSuchProcess:
            killed += 1
        except Exception as e:
            console.print(f"    [yellow][SKIP][/yellow] PID {p.pid} — {e}")
            failed += 1
    return killed, failed


def kill_pid(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        name = p.name()
        p.terminate()
        try:
            p.wait(timeout=2)
        except psutil.TimeoutExpired:
            p.kill()
        console.print(f"  [red][KILL][/red] PID {pid} ({name})")
        return True
    except psutil.NoSuchProcess:
        console.print(f"  [yellow]PID {pid} ya no existe[/yellow]")
        return False
    except Exception as e:
        console.print(f"  [red]Error matando PID {pid}: {e}[/red]")
        return False


def _ask_kill_bulk(procs: list, label: str, auto: bool = False) -> list:
    if not procs:
        return []
    pids = ", ".join(str(p.pid) for p in procs)
    console.print(f"\n  [bold]{label}[/bold] ({len(procs)})  PIDs: [dim]{pids}[/dim]")
    if auto:
        return procs
    if Confirm.ask("  ¿Eliminar todos?", default=False):
        return procs
    # Individual si rechaza el bulk
    approved = []
    for p in procs:
        try:
            cpu = safe_cpu(p)
            mb  = safe_mem_mb(p)
            console.print(
                f"    PID [cyan]{p.pid}[/cyan]  {p.name():<20}  "
                f"CPU {cpu:.1f}%  {mb:.0f} MB  uptime {runtime_str(p)}"
            )
            if Confirm.ask("    ¿Eliminar?", default=False):
                approved.append(p)
        except psutil.NoSuchProcess:
            pass
    return approved


# ── Modos principales ──────────────────────────────────────────────────────────

def run_show():
    """Solo muestra procesos problemáticos y RAM — sin matar nada."""
    console.rule("[bold cyan]  SCRAPER PROCESS MONITOR — SHOW  [/bold cyan]")
    console.print("\n[dim]Escaneando...[/dim]")
    scan = scan_processes()
    console.print(mem_panel())

    total = sum(len(v) for v in scan.values())
    if total == 0:
        console.print(Panel("[green]✔  Sin procesos problemáticos detectados[/green]",
                            border_style="green"))
        return

    if scan["orphan_drivers"]:
        console.print(_proc_table(scan["orphan_drivers"],
                                  "Drivers huérfanos (geckodriver/chromedriver)",
                                  "red", show_cpu=False))
    if scan["heavy_browsers"]:
        console.print(_proc_table(scan["heavy_browsers"],
                                  f"Browsers con alto consumo "
                                  f"(CPU>{CPU_BROWSER_PCT}% o RAM>{RAM_BROWSER_MB}MB)",
                                  "magenta"))
    if scan["zombies"]:
        console.print(_zombie_table(scan["zombies"]))
    if scan["heavy_scrapers"]:
        console.print(_proc_table(scan["heavy_scrapers"],
                                  "Scrapers con alto consumo", "yellow"))

    console.print(f"\n[yellow]Total: [bold]{total}[/bold] proceso(s) problemáticos.[/yellow]")
    console.rule()


def run_top(n: int = 15):
    """Muestra top N procesos del sistema por CPU + RAM."""
    console.rule("[bold cyan]  TOP PROCESOS  [/bold cyan]")
    console.print(mem_panel())
    rows = scan_top(n)
    if not rows:
        console.print("[dim]Sin procesos relevantes.[/dim]")
    else:
        console.print(_top_table(rows))
    console.rule()


def run_kill_pid(pid: int):
    """Mata un PID específico con confirmación."""
    try:
        p = psutil.Process(pid)
        cpu = safe_cpu(p)
        mb  = safe_mem_mb(p)
        console.print(f"\n  PID [cyan]{pid}[/cyan]  {p.name()}  "
                      f"CPU {cpu:.1f}%  {mb:.0f} MB  uptime {runtime_str(p)}")
        console.print(f"  Cmd: [dim]{safe_cmd(p)[:80]}[/dim]")
        if Confirm.ask("\n  ¿Eliminar este proceso?", default=False):
            kill_pid(pid)
    except psutil.NoSuchProcess:
        console.print(f"[red]PID {pid} no existe.[/red]")


def run_interactive(auto: bool = False):
    console.rule("[bold red]  SCRAPER PROCESS MONITOR  [/bold red]")
    console.print("\n[dim]Escaneando procesos...[/dim]")

    scan_before = scan_processes()
    scan_before["_vm_used_gb"] = psutil.virtual_memory().used / 1_073_741_824

    console.print(mem_panel("— ANTES —"))

    total_issues = sum(len(v) for k, v in scan_before.items()
                       if not k.startswith("_"))

    if total_issues == 0:
        console.print(Panel("[green]✔  Sin problemas detectados — sistema limpio[/green]",
                            border_style="green"))
        return

    # Mostrar tablas
    if scan_before["orphan_drivers"]:
        console.print(_proc_table(scan_before["orphan_drivers"],
                                  "Drivers huérfanos", "red", show_cpu=False))
    if scan_before["heavy_browsers"]:
        console.print(_proc_table(scan_before["heavy_browsers"],
                                  f"Browsers pesados (CPU>{CPU_BROWSER_PCT}% o "
                                  f"RAM>{RAM_BROWSER_MB}MB)", "magenta"))
    if scan_before["zombies"]:
        console.print(_zombie_table(scan_before["zombies"]))
    if scan_before["heavy_scrapers"]:
        console.print(_proc_table(scan_before["heavy_scrapers"],
                                  "Scrapers pesados", "yellow"))

    console.print(f"\n[yellow]Se encontraron [bold]{total_issues}[/bold] "
                  f"proceso(s) problemáticos.[/yellow]")

    # Aprobación
    console.rule("[dim]Confirmación[/dim]")
    to_kill  = _ask_kill_bulk(scan_before["orphan_drivers"],
                              "Drivers huérfanos", auto)
    to_kill += _ask_kill_bulk(scan_before["heavy_browsers"],
                              "Browsers pesados", auto)
    to_kill += _ask_kill_bulk(scan_before["heavy_scrapers"],
                              "Scrapers pesados", auto)

    if scan_before["zombies"]:
        console.print(
            f"\n  [dim]{len(scan_before['zombies'])} zombie(s): ya terminaron, "
            f"se limpian solos. Para forzar, usa --pid <ppid>.[/dim]"
        )

    # Opción de matar PID extra
    if not auto:
        extra = Prompt.ask(
            "\n  PIDs adicionales a matar (separados por coma, Enter para omitir)",
            default=""
        ).strip()
        if extra:
            for raw in extra.split(","):
                raw = raw.strip()
                if raw.isdigit():
                    try:
                        to_kill.append(psutil.Process(int(raw)))
                    except psutil.NoSuchProcess:
                        console.print(f"  [yellow]PID {raw} no existe[/yellow]")

    # Ejecución
    if not to_kill:
        console.print("\n[dim]Sin cambios aplicados.[/dim]")
    else:
        console.print(f"\n[bold]Eliminando {len(to_kill)} proceso(s)...[/bold]")
        killed, failed = execute_kills(to_kill)
        console.print(f"\n  Eliminados: [green]{killed}[/green]  "
                      f"Fallidos: [{'red' if failed else 'dim'}]{failed}"
                      f"[/{'red' if failed else 'dim'}]")
        time.sleep(1.5)

    # Re-escaneo y resumen
    console.print("\n[dim]Re-escaneando...[/dim]")
    scan_after = scan_processes()
    console.print(mem_panel("— DESPUÉS —"))
    console.print(_summary_table(scan_before, scan_after))
    console.rule()


# ── Tests ──────────────────────────────────────────────────────────────────────

def run_tests():
    console.rule("[bold cyan]  TESTS  [/bold cyan]")
    results = []

    def check(name, ok, detail=""):
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        console.print(f"  {status}  {name}" +
                      (f"  [dim]{detail}[/dim]" if detail else ""))
        results.append((name, ok))

    try:
        psutil.cpu_percent()
        check("psutil funcional", True)
    except Exception as e:
        check("psutil funcional", False, str(e))

    scan = scan_processes()
    expected = {"orphan_drivers", "heavy_browsers", "zombies", "heavy_scrapers"}
    check("scan_processes() claves correctas",
          expected.issubset(scan.keys()), str(set(scan.keys())))
    check("scan_processes() devuelve listas",
          all(isinstance(v, list) for k, v in scan.items() if not k.startswith("_")))

    try:
        mem_panel("test")
        check("mem_panel() sin error", True)
    except Exception as e:
        check("mem_panel() sin error", False, str(e))

    me = psutil.Process(os.getpid())
    mb = safe_mem_mb(me)
    check("safe_mem_mb() > 0", mb > 0, f"{mb:.1f} MB")

    me.cpu_percent(interval=None)
    time.sleep(0.2)
    cpu = safe_cpu(me)
    check("safe_cpu() es float", isinstance(cpu, float), f"{cpu:.1f}%")

    rt = runtime_str(me)
    check("runtime_str() no vacío", bool(rt), rt)

    rows = scan_top(5)
    check("scan_top(5) devuelve lista", isinstance(rows, list),
          f"{len(rows)} filas")

    k, f = execute_kills([])
    check("execute_kills([]) → (0,0)", (k, f) == (0, 0), str((k, f)))

    port_result = _python_connected_to_port(99999)
    check("_python_connected_to_port(inexistente) → False",
          port_result is False)

    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    color  = "green" if passed == total else "yellow" if passed > total//2 else "red"
    console.rule()
    console.print(f"\n  [{color}]Tests: {passed}/{total} OK[/{color}]\n")
    return passed == total


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Monitor y limpiador de procesos del scraper"
    )
    parser.add_argument("--show",  action="store_true",
                        help="Mostrar procesos problemáticos sin matar")
    parser.add_argument("--auto",  action="store_true",
                        help="Eliminar problemáticos sin pedir confirmación")
    parser.add_argument("--top",   type=int, metavar="N", nargs="?", const=15,
                        help="Mostrar top N procesos por CPU+RAM (default 15)")
    parser.add_argument("--pid",   type=int, metavar="PID",
                        help="Matar un PID específico")
    parser.add_argument("--test",  action="store_true",
                        help="Ejecutar tests de verificación")
    args = parser.parse_args()

    if args.test:
        sys.exit(0 if run_tests() else 1)
    elif args.show:
        run_show()
    elif args.top is not None:
        run_top(args.top)
    elif args.pid is not None:
        run_kill_pid(args.pid)
    else:
        run_interactive(auto=args.auto)


if __name__ == "__main__":
    main()
