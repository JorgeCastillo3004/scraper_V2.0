"""
test_login.py — Prueba robustez de la función login()

Escenarios testeados:
  1. Login normal correcto
  2. Login con \n en el password (debe funcionar igual)
  3. Login con password incorrecto (debe fallar con RuntimeError)
  4. Login con página en estado raro (modal abierto) — usa ESC
"""

import sys
import os
import time
import traceback

sys.path.insert(0, '/home/you/work_2026')
os.chdir('/home/you/work_2026')

from common_functions import launch_navigator, login

EMAIL    = "jignacio@jweglobal.com"
PASSWORD = "Caracas5050@"

results = []

def report(test_name, passed, detail=""):
    status = "✓ PASS" if passed else "✗ FAIL"
    results.append((test_name, passed, detail))
    print(f"\n  {status} — {test_name}")
    if detail:
        print(f"         {detail}")


# ─────────────────────────────────────────────────────────────
# TEST 1 — Login correcto
# ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 1 — Login con credenciales correctas")
print("="*60)
driver = None
try:
    driver = launch_navigator('https://www.flashscore.com', headless=True)
    login(driver, email_=EMAIL, password_=PASSWORD)
    # Verificar que hay sesión activa
    user_els = driver.find_elements("xpath", '//*[contains(@class,"header__text--loggedIn")]')
    passed = len(user_els) > 0
    report("Login correcto", passed, f"loggedIn encontrado: {len(user_els)} elemento(s)")
except Exception as e:
    report("Login correcto", False, str(e))
finally:
    if driver:
        driver.quit()
        time.sleep(2)


# ─────────────────────────────────────────────────────────────
# TEST 2 — Login con \n en password
# ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 2 — Login con \\n en el password")
print("="*60)
driver = None
try:
    driver = launch_navigator('https://www.flashscore.com', headless=True)
    login(driver, email_=EMAIL, password_=PASSWORD + "\n")
    user_els = driver.find_elements("xpath", '//*[contains(@class,"header__text--loggedIn")]')
    passed = len(user_els) > 0
    report("Login con \\n en password", passed, f"loggedIn encontrado: {len(user_els)} elemento(s)")
except Exception as e:
    report("Login con \\n en password", False, str(e))
finally:
    if driver:
        driver.quit()
        time.sleep(2)


# ─────────────────────────────────────────────────────────────
# TEST 3 — Password incorrecto (debe fallar con RuntimeError)
# ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 3 — Password incorrecto (debe lanzar RuntimeError)")
print("="*60)
driver = None
try:
    driver = launch_navigator('https://www.flashscore.com', headless=True)
    login(driver, email_=EMAIL, password_="password_incorrecto_123", max_attempts=1)
    report("Password incorrecto detectado", False, "No lanzó excepción — debería haber fallado")
except RuntimeError as e:
    report("Password incorrecto detectado", True, f"RuntimeError capturado correctamente: {str(e)[:80]}")
except Exception as e:
    report("Password incorrecto detectado", False, f"Excepción inesperada: {e}")
finally:
    if driver:
        driver.quit()
        time.sleep(2)


# ─────────────────────────────────────────────────────────────
# TEST 4 — Login después de enviar ESC múltiples veces
# ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("TEST 4 — Login con ESC previo (simula modal abierto)")
print("="*60)
driver = None
try:
    from selenium import webdriver
    from selenium.webdriver.common.keys import Keys
    driver = launch_navigator('https://www.flashscore.com', headless=True)
    # Simular que la página está en estado raro — enviamos ESC varias veces
    for _ in range(3):
        webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.5)
    # Ahora intentar login
    login(driver, email_=EMAIL, password_=PASSWORD)
    user_els = driver.find_elements("xpath", '//*[contains(@class,"header__text--loggedIn")]')
    passed = len(user_els) > 0
    report("Login tras ESC múltiples", passed, f"loggedIn encontrado: {len(user_els)} elemento(s)")
except Exception as e:
    report("Login tras ESC múltiples", False, str(e))
finally:
    if driver:
        driver.quit()
        time.sleep(2)


# ─────────────────────────────────────────────────────────────
# RESUMEN
# ─────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("RESUMEN DE PRUEBAS")
print("="*60)
passed_count = sum(1 for _, p, _ in results if p)
for name, passed, detail in results:
    status = "✓" if passed else "✗"
    print(f"  {status}  {name}")
    if detail:
        print(f"     → {detail}")
print(f"\n  Resultado: {passed_count}/{len(results)} tests pasados")
print("="*60)
