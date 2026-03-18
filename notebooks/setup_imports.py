"""
setup_imports.py

Configura sys.path y el working directory para que todos los módulos
del proyecto sean accesibles desde el notebook.

Uso en la celda 1 del notebook:
    from setup_imports import *
"""

import sys
import os

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SRC_DIR      = os.path.join(PROJECT_ROOT, 'src')

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Working directory al raíz del proyecto
# (necesario para resolver check_points/, config.py y rutas relativas)
os.chdir(PROJECT_ROOT)

# ── Imports del proyecto ───────────────────────────────────────────────────────
from common_functions import *
from data_base import *
from milestone1 import *
from milestone2 import *
from milestone3 import *
from milestone4 import *
from milestone6 import *
from milestone7 import *
from milestone8 import *
from main import *

print(f"[OK] PROJECT_ROOT : {PROJECT_ROOT}")
print(f"[OK] cwd          : {os.getcwd()}")
print(f"[OK] sys.path[0]  : {sys.path[0]}")
