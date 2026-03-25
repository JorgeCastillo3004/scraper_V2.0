#!/usr/bin/env python3
"""
inspect_processes.py
Visualiza procesos zombie y drivers huérfanos del scraper.
Uso:
  python3 scripts/inspect_processes.py          # solo visualizar
  python3 scripts/inspect_processes.py --kill   # visualizar y matar
"""

import argparse
import sys
import psutil


# ── Colores ANSI ──────────────────────────────────────────────────────────────
R  = "\033[91m"   # rojo
Y  = "\033[93m"   # amarillo
G  = "\033[92m"   # verde
B  = "\033[94m"   # azul
C  = "\033[96m"   # cyan
W  = "\033[97m"   # blanco brillante
DIM = "\033[2m"   # tenue
RST = "\033[0m"   # reset

# ── Palabras clave que identifican drivers/browsers del scraper ───────────────
DRIVER_KEYWORDS  = ["geckodriver", "chromedriver", "firefox-bin", "firefox", "chrome"]
SELENIUM_MARKERS = ["marionette", "--marionette"]   # Firefox controlado por Selenium
JUPYTER_MARKERS  = ["nbserver", "jupyter", "ipykernel"]


def mem_mb(proc):
    try:
        return proc.memory_info().rss / 1_048_576
    except Exception:
        return 0.0


def cmdline_str(proc):
    try:
        parts = proc.cmdline()
        return " ".join(parts) if parts else proc.name()
    except Exception:
        return proc.name()


def parent_alive(proc):
    try:
        parent = psutil.Process(proc.ppid())
        return parent.is_running() and parent.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def is_essential(proc):
    """True si el proceso pertenece a Selenium activo o a Jupyter."""
    cmd = cmdline_str(proc)
    return any(m in cmd for m in SELENIUM_MARKERS + JUPYTER_MARKERS)


def find_zombies():
    """Procesos en estado zombie (Z) del sistema."""
    zombies = []
    for p in psutil.process_iter(['pid', 'name', 'status', 'ppid']):
        try:
            if p.info['status'] == psutil.STATUS_ZOMBIE:
                zombies.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return zombies


def find_orphan_drivers():
    """Firefox/geckodriver/chrome sin parent vivo y sin markers esenciales."""
    orphans = []
    for p in psutil.process_iter(['pid', 'name', 'status', 'ppid']):
        try:
            name = p.info['name'].lower()
            if not any(k in name for k in DRIVER_KEYWORDS):
                continue
            if is_essential(p):
                continue
            if not parent_alive(p):
                orphans.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return orphans


def find_all_drivers():
    """Todos los procesos driver/browser activos (para contexto)."""
    drivers = []
    for p in psutil.process_iter(['pid', 'name', 'status', 'ppid']):
        try:
            name = p.info['name'].lower()
            if any(k in name for k in DRIVER_KEYWORDS):
                drivers.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return drivers


def ram_summary():
    vm = psutil.virtual_memory()
    used_gb  = vm.used  / 1_073_741_824
    total_gb = vm.total / 1_073_741_824
    pct      = vm.percent
    color    = R if pct > 85 else Y if pct > 65 else G
    bar_len  = 30
    filled   = int(bar_len * pct / 100)
    bar      = "█" * filled + "░" * (bar_len - filled)
    return f"{color}[{bar}]{RST} {used_gb:.1f} GB / {total_gb:.1f} GB  ({pct}%)"


# ── Sección: zombies ───────────────────────────────────────────────────────────
def print_zombies(zombies):
    print(f"\n{W}{'═'*60}{RST}")
    print(f"{W}  PROCESOS ZOMBIE  ({len(zombies)} encontrados){RST}")
    print(f"{W}{'═'*60}{RST}")

    if not zombies:
        print(f"  {G}✔  Sin zombies{RST}")
        return

    print(f"  {DIM}{'PID':<8} {'NOMBRE':<20} {'PPID':<8} {'PARENT'}{RST}")
    print(f"  {'─'*56}")
    for p in zombies:
        try:
            ppid = p.ppid()
            try:
                parent_name = psutil.Process(ppid).name()
            except Exception:
                parent_name = "? (muerto)"
            print(f"  {R}{p.pid:<8}{RST} {p.name():<20} {ppid:<8} {DIM}{parent_name}{RST}")
        except Exception:
            pass


# ── Sección: drivers ──────────────────────────────────────────────────────────
def print_drivers(all_drivers, orphans):
    orphan_pids = {p.pid for p in orphans}

    print(f"\n{W}{'═'*60}{RST}")
    print(f"{W}  DRIVERS / BROWSERS  ({len(all_drivers)} total | {len(orphans)} huérfanos){RST}")
    print(f"{W}{'═'*60}{RST}")

    if not all_drivers:
        print(f"  {DIM}Sin procesos driver activos{RST}")
        return

    print(f"  {DIM}{'PID':<8} {'NOMBRE':<18} {'MB':>6}  {'ESTADO':<12} {'TIPO'}{RST}")
    print(f"  {'─'*56}")

    for p in sorted(all_drivers, key=mem_mb, reverse=True):
        try:
            mb     = mem_mb(p)
            status = p.status()
            cmd    = cmdline_str(p)

            if p.pid in orphan_pids:
                tag   = f"{R}HUÉRFANO{RST}"
                pid_c = R
            elif is_essential(p):
                tag   = f"{G}ESENCIAL{RST}"
                pid_c = G
            else:
                tag   = f"{Y}activo{RST}"
                pid_c = Y

            # Etiqueta de rol
            if "marionette" in cmd:
                role = f"{C}[selenium]{RST}"
            elif any(m in cmd for m in JUPYTER_MARKERS):
                role = f"{B}[jupyter]{RST}"
            elif "geckodriver" in p.name().lower():
                role = f"{C}[geckodriver]{RST}"
            else:
                role = ""

            print(f"  {pid_c}{p.pid:<8}{RST} {p.name():<18} {mb:>6.1f}  {tag:<12} {role}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


# ── Matar procesos ────────────────────────────────────────────────────────────
def kill_processes(zombies, orphans):
    targets = orphans  # los zombies no se pueden matar directamente (ya terminaron)
    if not targets:
        print(f"\n  {G}Nada que matar.{RST}")
        return

    print(f"\n{Y}  ¿Matar {len(targets)} proceso(s) huérfano(s)? [s/N]: {RST}", end="")
    resp = input().strip().lower()
    if resp != "s":
        print(f"  {DIM}Cancelado.{RST}")
        return

    killed = 0
    for p in targets:
        try:
            p.kill()
            print(f"  {R}[KILL]{RST} PID {p.pid} ({p.name()})")
            killed += 1
        except Exception as e:
            print(f"  {Y}[SKIP]{RST} PID {p.pid} — {e}")

    if zombies:
        print(f"\n  {DIM}Nota: {len(zombies)} zombie(s) no se eliminan directamente.")
        print(f"  Son limpiados por su proceso padre o al reiniciar.{RST}")

    print(f"\n  {G}Procesos eliminados: {killed}{RST}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Inspecciona procesos zombie y drivers huérfanos"
    )
    parser.add_argument("--kill", action="store_true",
                        help="Ofrecer matar los huérfanos encontrados")
    args = parser.parse_args()

    print(f"\n{W}{'═'*60}{RST}")
    print(f"{W}  MEMORIA RAM{RST}")
    print(f"{W}{'═'*60}{RST}")
    print(f"  {ram_summary()}")

    zombies     = find_zombies()
    all_drivers = find_all_drivers()
    orphans     = find_orphan_drivers()

    print_zombies(zombies)
    print_drivers(all_drivers, orphans)

    if args.kill:
        kill_processes(zombies, orphans)
    else:
        total_issues = len(zombies) + len(orphans)
        if total_issues:
            print(f"\n  {Y}Tip: ejecuta con --kill para limpiar los {total_issues} problema(s){RST}")

    print()


if __name__ == "__main__":
    main()
