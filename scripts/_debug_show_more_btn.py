"""_debug_show_more_btn — encontrar el botón 'Show more matches' de forma ÚNICA.
Reusa el driver vivo (NO navega, NO quit). Solo lee el DOM."""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts')); sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from selenium.webdriver.common.by import By

d = get_driver()
print('URL:', d.current_url)
print('=' * 70)


def probe(label, by, sel):
    try:
        els = d.find_elements(by, sel)
        vis = [e for e in els if e.is_displayed()]
        print('  %-58s -> %d (visibles %d)' % (label, len(els), len(vis)))
        return els
    except Exception as e:
        print('  %-58s -> ERROR %s' % (label, e))
        return []


print('\n[A] Candidatos por el SPAN del texto:')
probe("span[text()='Show more matches']",        By.XPATH, "//span[text()='Show more matches']")
probe("span[@data-testid='wcl-scores-caption-05']", By.XPATH, "//span[@data-testid='wcl-scores-caption-05']")
probe("CSS span[data-testid=wcl-scores-caption-05]", By.CSS_SELECTOR, "span[data-testid='wcl-scores-caption-05']")

print('\n[B] Selectores clásicos de FlashScore:')
probe("a.event__more",                 By.CSS_SELECTOR, "a.event__more")
probe(".event__more",                  By.CSS_SELECTOR, ".event__more")
probe("[class*='event__more']",        By.CSS_SELECTOR, "[class*='event__more']")

print('\n[C] Ancestro clickeable que CONTIENE el span del texto:')
probe("button[.//span[text()='Show more matches']]",   By.XPATH, "//button[.//span[text()='Show more matches']]")
probe("a[.//span[text()='Show more matches']]",        By.XPATH, "//a[.//span[text()='Show more matches']]")
probe("*[@role='button'][.//span[text()='Show more matches']]", By.XPATH, "//*[@role='button'][.//span[text()='Show more matches']]")

print('\n[D] Inspección de ancestros del span (tag/class/role/testid/onclick):')
spans = d.find_elements(By.XPATH, "//span[text()='Show more matches']")
if not spans:
    print('  No hay span "Show more matches" en esta página (¿ya cargó todo o no es results?).')
else:
    el = spans[0]
    for lvl in range(6):
        if el is None:
            break
        tag  = el.tag_name
        cls  = (el.get_attribute('class') or '')[:60]
        role = el.get_attribute('role')
        tid  = el.get_attribute('data-testid')
        clk  = 'sí' if el.get_attribute('onclick') else ''
        print('  [nivel %d] <%s> class="%s" role=%s testid=%s onclick=%s' % (lvl, tag, cls, role, tid, clk))
        try:
            el = el.find_element(By.XPATH, '..')
        except Exception:
            break
