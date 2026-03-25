#!/usr/bin/env python3
"""
stop_process.py
───────────────
Monitor interactivo de procesos para el scraper.

Detecta y permite eliminar:
  - Drivers / browsers huérfanos (Chrome, Firefox, geckodriver)
  - Procesos zombie
  - Procesos del scraper con CPU o RAM excesiva
  - Instancias colgadas de main2.py / paralel_execution.py

Uso:
    python scripts/stop_process.py            # modo interactivo
    python scripts/stop_process.py --auto     # mata huérfanos sin preguntar
    python scripts/stop_process.py --test     # ejecuta tests de verificación
"""

import argparse
import os
import sys
import time

import psutil
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import box
from rich.text import Text
from rich.columns import Columns

console = Console()

# ── Configuración ──────────────────────────────────────────────────────────────

DRIVER_KEYWORDS   = ["geckodriver", "chromedriver", "firefox-bin", "firefox", "chrome"]
SCRAPER_KEYWORDS  = ["main2.py", "paralel_execution.py", "milestone", "dashboard/app.py"]
SELENIUM_MARKERS  = ["marionette", "--marionette", "remote-debugging-port",
                     "disable-features=WebAssemblyTrapHandler"]
JUPYTER_MARKERS   = ["nbserver", "jupyter", "ipykernel"]

CPU_THRESHOLD_PCT = 60.0   # % CPU para considerar "excesivo" en procesos del scraper
RAM_THRESHOLD_MB  = 400    # MB RAM para considerar "excesivo"

# Procesos del sistema que NUNCA se tocan
SYSTEM_SAFELIST = [
    "networkd-dispatcher", "Xorg", "gnome-shell", "gdm", "systemd",
    "dbus", "pulseaudio", "pipewire", "redis-server", "postgres",
    "uvicorn",   # API del sistema
    "hidpi",     "pop-transition",
]


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
    """CPU% acumulado (no necesita intervalo de muestreo)."""
    try:
        return proc.cpu_percent(interval=None)
    except Exception:
        return 0.0


def parent_alive(proc: psutil.Process) -> bool:
    try:
        parent = psutil.Process(proc.ppid())
        return parent.is_running() and parent.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def is_safelist(proc: psutil.Process) -> bool:
    cmd = safe_cmd(proc)
    return any(s in cmd for s in SYSTEM_SAFELIST)


def is_selenium_active(proc: psutil.Process) -> bool:
    cmd = safe_cmd(proc)
    return any(m in cmd for m in SELENIUM_MARKERS)


def is_jupyter(proc: psutil.Process) -> bool:
    cmd = safe_cmd(proc)
    return any(m in cmd for m in JUPYTER_MARKERS)


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


# ── Escaneo de procesos ────────────────────────────────────────────────────────

def scan_processes() -> dict:
    """
    Retorna categorías de procesos a revisar:
      orphan_drivers  — drivers sin parent vivo y sin Selenium activo
      zombies         — estado Z
      heavy_scrapers  — procesos del scraper con CPU/RAM excesiva
    """
    # Calentar medición de CPU (necesita dos llamadas separadas)
    procs = list(psutil.process_iter(
        ['pid', 'name', 'status', 'ppid', 'username']
    ))
    for p in procs:
        try:
            p.cpu_percent(interval=None)   # primera llamada — siempre 0
        except Exception:
            pass
    time.sleep(0.5)                        # intervalo para medir CPU real

    result = {"orphan_drivers": [], "zombies": [], "heavy_scrapers": []}
    current_user = os.environ.get("USER", "")

    for p in procs:
        try:
            if p.info["username"] != current_user:
                continue
            if is_safelist(p):
                continue

            name = p.info["name"].lower()
            status = p.info["status"]

            # ── Zombie ──
            if status == psutil.STATUS_ZOMBIE:
                result["zombies"].append(p)
                continue

            # ── Driver huérfano ──
            if any(k in name for k in DRIVER_KEYWORDS):
                if not is_selenium_active(p) and not is_jupyter(p) and not parent_alive(p):
                    result["orphan_drivers"].append(p)

            # ── Scraper pesado ──
            cmd = safe_cmd(p)
            if any(k in cmd for k in SCRAPER_KEYWORDS):
                cpu = safe_cpu(p)
                mb  = safe_mem_mb(p)
                if cpu > CPU_THRESHOLD_PCT or mb > RAM_THRESHOLD_MB:
                    result["heavy_scrapers"].append(p)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return result


# ── Resumen de memoria ─────────────────────────────────────────────────────────

def mem_panel(label: str = "") -> Panel:
    vm   = psutil.virtual_memory()
    sw   = psutil.swap_memory()
    used = vm.used  / 1_073_741_824
    tot  = vm.total / 1_073_741_824
    pct  = vm.percent
    su   = sw.used  / 1_073_741_824

    bar_len = 28
    filled  = int(bar_len * pct / 100)
    color   = "red" if pct > 85 else "yellow" if pct > 65 else "green"
    bar     = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * (bar_len - filled)}[/dim]"

    text = Text.assemble(
        ("RAM  ", "bold white"),
        Text.from_markup(bar),
        f"  {used:.1f} / {tot:.1f} GB  ({pct}%)\n",
        ("Swap ", "bold white"),
        f"  {su:.1f} GB usado",
    )
    title = f"[bold]Memoria  {label}[/bold]"
    return Panel(text, title=title, border_style="dim", padding=(0, 1))


# ── Tablas de procesos ─────────────────────────────────────────────────────────

def _driver_table(procs: list, title: str, color: str) -> Table:
    t = Table(title=title, box=box.SIMPLE_HEAD, title_style=f"bold {color}")
    t.add_column("PID",     style=color, width=8)
    t.add_column("Nombre",  width=18)
    t.add_column("RAM MB",  justify="right", width=8)
    t.add_column("Uptime",  width=8)
    t.add_column("Cmdline", style="dim", max_width=50, no_wrap=True)
    for p in sorted(procs, key=safe_mem_mb, reverse=True):
        try:
            t.add_row(
                str(p.pid),
                p.name()[:18],
                f"{safe_mem_mb(p):.0f}",
                runtime_str(p),
                safe_cmd(p)[:50],
            )
        except psutil.NoSuchProcess:
            pass
    return t


def _scraper_table(procs: list) -> Table:
    t = Table(title="Scrapers con alto consumo", box=box.SIMPLE_HEAD,
              title_style="bold yellow")
    t.add_column("PID",    style="yellow", width=8)
    t.add_column("Nombre", width=22)
    t.add_column("CPU %",  justify="right", width=7)
    t.add_column("RAM MB", justify="right", width=8)
    t.add_column("Uptime", width=8)
    for p in sorted(procs, key=safe_cpu, reverse=True):
        try:
            cpu = safe_cpu(p)
            mb  = safe_mem_mb(p)
            cpu_color = "red" if cpu > 80 else "yellow"
            t.add_row(
                str(p.pid),
                safe_cmd(p).split("/")[-1][:22],
                f"[{cpu_color}]{cpu:.1f}[/{cpu_color}]",
                f"{mb:.0f}",
                runtime_str(p),
            )
        except psutil.NoSuchProcess:
            pass
    return t


def _zombie_table(procs: list) -> Table:
    t = Table(title="Procesos Zombie", box=box.SIMPLE_HEAD, title_style="bold red")
    t.add_column("PID",    style="red",  width=8)
    t.add_column("Nombre", width=20)
    t.add_column("PPID",   width=8)
    t.add_column("Parent", style="dim", width=20)
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


def _summary_table(before: dict, after: dict) -> Table:
    """Tabla comparativa antes / después."""
    def count(d, key):
        return len(d.get(key, []))

    def mb_total(d, key):
        return sum(safe_mem_mb(p) for p in d.get(key, []))

    vm_before = before.get("_vm_used_gb", 0)
    vm_after  = psutil.virtual_memory().used / 1_073_741_824

    t = Table(title="Resumen de limpieza", box=box.ROUNDED,
              title_style="bold green", border_style="green")
    t.add_column("Categoría",          style="bold", width=25)
    t.add_column("Antes",  justify="right", width=10)
    t.add_column("Después", justify="right", width=10)
    t.add_column("Δ",      justify="right", width=10)

    def row(label, b, a, unit=""):
        diff = a - b
        sign = "+" if diff > 0 else ""
        color = "red" if diff > 0 else "green" if diff < 0 else "dim"
        t.add_row(
            label,
            f"{b:.0f}{unit}",
            f"{a:.0f}{unit}",
            f"[{color}]{sign}{diff:.0f}{unit}[/{color}]",
        )

    row("Drivers huérfanos",
        count(before, "orphan_drivers"),
        count(after,  "orphan_drivers"))
    row("Zombies",
        count(before, "zombies"),
        count(after,  "zombies"))
    row("Scrapers pesados",
        count(before, "heavy_scrapers"),
        count(after,  "heavy_scrapers"))
    row("RAM usada",
        vm_before * 1024,
        vm_after  * 1024,
        " MB")
    return t


# ── Aprobación y ejecución ─────────────────────────────────────────────────────

def _ask_kill_bulk(procs: list, label: str) -> list:
    """Pregunta si matar el grupo completo; devuelve la lista aprobada."""
    if not procs:
        return []
    pids = ", ".join(str(p.pid) for p in procs)
    console.print(f"\n  [bold]{label}[/bold] ({len(procs)} proceso(s))  PIDs: {pids}")
    if Confirm.ask("  ¿Eliminar todos?", default=False):
        return procs
    # Si rechaza el bulk, preguntar individualmente
    approved = []
    for p in procs:
        try:
            console.print(
                f"    PID [cyan]{p.pid}[/cyan]  {p.name():<18}  "
                f"{safe_mem_mb(p):.0f} MB  uptime {runtime_str(p)}"
            )
            if Confirm.ask("    ¿Eliminar este proceso?", default=False):
                approved.append(p)
        except psutil.NoSuchProcess:
            pass
    return approved


def execute_kills(targets: list) -> tuple[int, int]:
    """Mata la lista de procesos. Retorna (killed, failed)."""
    killed = failed = 0
    for p in targets:
        try:
            pid  = p.pid
            name = p.name()
            p.terminate()
            time.sleep(0.4)
            if p.is_running():
                p.kill()
            console.print(f"    [red][KILL][/red] PID {pid} ({name})")
            killed += 1
        except psutil.NoSuchProcess:
            killed += 1   # ya murió, cuenta como éxito
        except Exception as e:
            console.print(f"    [yellow][SKIP][/yellow] PID {p.pid} — {e}")
            failed += 1
    return killed, failed


# ── Interfaz principal ─────────────────────────────────────────────────────────

def run_interactive(auto: bool = False):
    console.rule("[bold red]  SCRAPER PROCESS MONITOR  [/bold red]")

    # ── Escaneo inicial ──
    console.print("\n[dim]Escaneando procesos...[/dim]")
    scan_before = scan_processes()
    scan_before["_vm_used_gb"] = psutil.virtual_memory().used / 1_073_741_824

    # ── Mostrar estado de RAM ──
    console.print(mem_panel("— ANTES —"))

    # ── Mostrar procesos encontrados ──
    total_issues = (
        len(scan_before["orphan_drivers"]) +
        len(scan_before["zombies"]) +
        len(scan_before["heavy_scrapers"])
    )

    if total_issues == 0:
        console.print(
            Panel("[green]✔  Sin problemas detectados — sistema limpio[/green]",
                  border_style="green")
        )
        return

    if scan_before["orphan_drivers"]:
        console.print(_driver_table(scan_before["orphan_drivers"],
                                    "Drivers / browsers huérfanos", "red"))
    if scan_before["zombies"]:
        console.print(_zombie_table(scan_before["zombies"]))
    if scan_before["heavy_scrapers"]:
        console.print(_scraper_table(scan_before["heavy_scrapers"]))

    console.print(
        f"\n[yellow]Se encontraron [bold]{total_issues}[/bold] proceso(s) problemáticos.[/yellow]"
    )

    # ── Aprobación ──
    if auto:
        to_kill = (
            scan_before["orphan_drivers"] +
            scan_before["heavy_scrapers"]
        )
        console.print("[yellow]  Modo --auto: eliminando sin confirmación...[/yellow]")
    else:
        console.rule("[dim]Confirmación[/dim]")
        to_kill  = _ask_kill_bulk(scan_before["orphan_drivers"], "Drivers huérfanos")
        to_kill += _ask_kill_bulk(scan_before["heavy_scrapers"],  "Scrapers pesados")

        if scan_before["zombies"]:
            console.print(
                f"\n  [dim]Nota: {len(scan_before['zombies'])} zombie(s) no se pueden "
                f"matar directamente (ya terminaron). Se limpian solos al reiniciar.[/dim]"
            )

    # ── Ejecución ──
    if not to_kill:
        console.print("\n[dim]Sin cambios aplicados.[/dim]")
    else:
        console.print(f"\n[bold]Eliminando {len(to_kill)} proceso(s)...[/bold]")
        killed, failed = execute_kills(to_kill)
        console.print(f"\n  Eliminados: [green]{killed}[/green]  "
                      f"Fallidos: [{'red' if failed else 'dim'}]{failed}[/{'red' if failed else 'dim'}]")

        time.sleep(1)   # esperar a que el SO libere memoria

    # ── Escaneo posterior ──
    console.print("\n[dim]Re-escaneando...[/dim]")
    scan_after = scan_processes()

    # ── Tabla resumen ──
    console.print(mem_panel("— DESPUÉS —"))
    console.print(_summary_table(scan_before, scan_after))

    # ── Drivers activos restantes ──
    remaining_drivers = [
        p for p in psutil.process_iter(['pid', 'name'])
        if any(k in p.info['name'].lower() for k in DRIVER_KEYWORDS)
    ]
    if remaining_drivers:
        console.print(
            _driver_table(remaining_drivers, "Drivers activos restantes", "yellow")
        )
    else:
        console.print("[green]  ✔  Sin drivers activos[/green]")

    console.rule()


# ── Tests de verificación ──────────────────────────────────────────────────────

def run_tests():
    console.rule("[bold cyan]  TESTS DE VERIFICACIÓN  [/bold cyan]")
    results = []

    def check(name: str, ok: bool, detail: str = ""):
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        console.print(f"  {status}  {name}" + (f"  [dim]{detail}[/dim]" if detail else ""))
        results.append((name, ok))

    # ── Test 1: psutil disponible ──
    try:
        psutil.cpu_percent()
        check("psutil importable y funcional", True)
    except Exception as e:
        check("psutil importable y funcional", False, str(e))

    # ── Test 2: scan_processes retorna estructura correcta ──
    scan = scan_processes()
    expected_keys = {"orphan_drivers", "zombies", "heavy_scrapers"}
    check("scan_processes() retorna claves correctas",
          expected_keys.issubset(scan.keys()),
          str(set(scan.keys())))

    # ── Test 3: todos los valores son listas ──
    all_lists = all(isinstance(v, list) for k, v in scan.items() if not k.startswith("_"))
    check("scan_processes() retorna listas", all_lists)

    # ── Test 4: mem_panel no lanza excepciones ──
    try:
        mem_panel("test")
        check("mem_panel() sin excepciones", True)
    except Exception as e:
        check("mem_panel() sin excepciones", False, str(e))

    # ── Test 5: safe_mem_mb con proceso real ──
    try:
        me = psutil.Process(os.getpid())
        mb = safe_mem_mb(me)
        check("safe_mem_mb() retorna valor positivo", mb > 0, f"{mb:.1f} MB")
    except Exception as e:
        check("safe_mem_mb() retorna valor positivo", False, str(e))

    # ── Test 6: safe_cpu retorna float ──
    try:
        me = psutil.Process(os.getpid())
        me.cpu_percent(interval=None)
        time.sleep(0.2)
        cpu = safe_cpu(me)
        check("safe_cpu() retorna float", isinstance(cpu, float), f"{cpu:.1f}%")
    except Exception as e:
        check("safe_cpu() retorna float", False, str(e))

    # ── Test 7: runtime_str ──
    try:
        me = psutil.Process(os.getpid())
        rt = runtime_str(me)
        check("runtime_str() retorna string no vacío", bool(rt), rt)
    except Exception as e:
        check("runtime_str()", False, str(e))

    # ── Test 8: is_safelist protege procesos del sistema ──
    safe_found = False
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if "redis" in p.name().lower() or "uvicorn" in safe_cmd(p):
                safe_found = True
                safe_ok = is_safelist(p)
                check(f"is_safelist() protege {p.name()}", safe_ok)
                break
        except Exception:
            pass
    if not safe_found:
        check("is_safelist() — no hay proceso safelist activo para probar",
              True, "omitido")

    # ── Test 9: _driver_table y _summary_table no lanzan excepciones ──
    try:
        _driver_table([], "test", "green")
        _summary_table(
            {"orphan_drivers": [], "zombies": [], "heavy_scrapers": [], "_vm_used_gb": 0},
            {"orphan_drivers": [], "zombies": [], "heavy_scrapers": []}
        )
        check("tablas Rich se generan sin excepciones", True)
    except Exception as e:
        check("tablas Rich se generan sin excepciones", False, str(e))

    # ── Test 10: execute_kills con lista vacía ──
    try:
        k, f = execute_kills([])
        check("execute_kills([]) retorna (0, 0)", (k, f) == (0, 0), str((k, f)))
    except Exception as e:
        check("execute_kills([]) retorna (0, 0)", False, str(e))

    # ── Resultado global ──
    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    color  = "green" if passed == total else "yellow" if passed > total // 2 else "red"
    console.rule()
    console.print(
        f"\n  [{color}]Tests: {passed}/{total} OK[/{color}]\n"
    )
    return passed == total


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Monitor y limpiador de procesos del scraper"
    )
    parser.add_argument("--auto",  action="store_true",
                        help="Eliminar huérfanos sin pedir confirmación")
    parser.add_argument("--test",  action="store_true",
                        help="Ejecutar tests de verificación")
    args = parser.parse_args()

    if args.test:
        ok = run_tests()
        sys.exit(0 if ok else 1)

    run_interactive(auto=args.auto)


if __name__ == "__main__":
    main()
