import os
import re
import calendar
import threading
import unicodedata
import pymysql
from bs4 import BeautifulSoup
from datetime import date
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(".env")

LOGIN_URL = os.getenv("LOGIN_URL")
REP_URL = os.getenv("REP_VENT_PROD")
USER = os.getenv("DATUM_USER")
PASSWORD = os.getenv("DATUM_PASSWORD")
FECHA_INI = os.getenv("FECHA_INICIO")
FECHA_FIN = os.getenv("FECHA_FIN")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "autocommit": True
}

conn = pymysql.connect(**DB_CONFIG)
cursor = conn.cursor(pymysql.cursors.DictCursor)


def make_cursor():
    """Crea una conexión y cursor independiente para cada worker thread."""
    c = pymysql.connect(**DB_CONFIG)
    return c, c.cursor(pymysql.cursors.DictCursor)


def log(msg):
    print(f"[LOG] {msg}")


def generar_periodos_mensuales(fecha_inicio_str, fecha_fin_str):
    """Genera períodos mensuales entre dos fechas (DD/MM/YYYY).
    Si el mes final está incompleto, usa la fecha actual como límite."""
    d, m, y = fecha_inicio_str.split('/')
    inicio = date(int(y), int(m), int(d))

    d, m, y = fecha_fin_str.split('/')
    fin_global = min(date(int(y), int(m), int(d)), date.today())

    periodos = []
    current = date(inicio.year, inicio.month, 1)

    while current <= fin_global:
        periodo_inicio = max(current, inicio)
        ultimo_dia_mes = calendar.monthrange(current.year, current.month)[1]
        fin_mes = date(current.year, current.month, ultimo_dia_mes)
        periodo_fin = min(fin_mes, fin_global)

        periodos.append((
            periodo_inicio.strftime('%d/%m/%Y'),
            periodo_fin.strftime('%d/%m/%Y')
        ))

        current = date(current.year + (current.month // 12), (current.month % 12) + 1, 1)

    return periodos



def normalizar(texto):
    if not texto:
        return None
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = ''.join([c for c in texto if not unicodedata.combining(c)])
    texto = re.sub(r'[^a-z0-9\s]', '', texto)
    texto = re.sub(r'\s+', ' ', texto)
    return texto


def limpiar_producto(texto):
    if not texto:
        return None
    texto = texto.replace("+", "")
    return normalizar(texto)



TURNOS_HORAS = {
    1: [7,8,9,10,11,12,13],
    2: [14,15,16,17,18,19,20,21,22,23,0,1,2,3]
}

PLATILLOS = {}
PLATILLOS_BY_ID = {}
TIPOS = {}
DESCUENTOS = {}



def cargar_catalogos():
    global PLATILLOS, TIPOS, DESCUENTOS, PLATILLOS_BY_ID

    cursor.execute("SELECT id, nombre, costo_manual FROM platillos WHERE status=1")
    rows = cursor.fetchall()

    PLATILLOS = {normalizar(r["nombre"]): r for r in rows}
    PLATILLOS_BY_ID = {r["id"]: r for r in rows}

    cursor.execute("SELECT id, nombre FROM tipos_producto WHERE status=1")
    TIPOS = {normalizar(r["nombre"]): r["id"] for r in cursor.fetchall()}

    cursor.execute("""
        SELECT id, nombre, punto_venta_id
        FROM descuentos
        WHERE status = 1
    """)

    DESCUENTOS = {
        (normalizar(r["nombre"]), r["punto_venta_id"]): r["id"]
        for r in cursor.fetchall()
    }

    log(f"Platillos: {len(PLATILLOS)}")
    log(f"Tipos: {len(TIPOS)}")
    log(f"Descuentos: {len(DESCUENTOS)}")



def esperar_carga_completa(page, timeout_ms=120_000, estabilidad_ms=5_000, estabilidad_vacia_ms=3_000, min_espera_ms=8_000, polling_ms=1_500):
    """Espera a que el conteo de filas válidas se estabilice.
    - Con datos: retorna cuando lleva estabilidad_ms sin cambiar.
    - Sin datos: retorna cuando lleva estabilidad_vacia_ms en 0 filas y ya pasaron min_espera_ms
      desde el inicio (evita salir antes de que el servidor haya respondido)."""
    try:
        page.wait_for_function(
            """([estabilidad, estabilidad_vacia, min_espera]) => {
                const contar = () => Array.from(document.querySelectorAll("table tr"))
                    .filter(r => {
                        const tds = r.querySelectorAll("td");
                        return tds.length === 14 && !isNaN(parseInt(tds[3]?.innerText));
                    }).length;

                const ahora = Date.now();
                if (!window.__est) window.__est = { n: -1, t: ahora, inicio: ahora };

                const actual = contar();
                if (actual !== window.__est.n) {
                    window.__est.n = actual;
                    window.__est.t = ahora;
                    return false;
                }

                if (actual > 0 && (ahora - window.__est.t) >= estabilidad) return true;
                if (actual === 0 && (ahora - window.__est.inicio) >= min_espera && (ahora - window.__est.t) >= estabilidad_vacia) return true;
                return false;
            }""",
            arg=[estabilidad_ms, estabilidad_vacia_ms, min_espera_ms],
            timeout=timeout_ms,
            polling=polling_ms
        )
    except Exception:
        log("Tabla sin datos o timeout de carga")


def parsear(html):

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tr")

    data = []

    for row in rows:
        cols = row.find_all("td")

        if len(cols) != 14:
            continue

        try:
            producto_div = cols[1].find("div")
            producto_raw = producto_div.get("title") if producto_div else cols[1].get_text(strip=True)

            tipo_raw = cols[2].get_text(strip=True)
            cantidad_txt = cols[3].get_text(strip=True)

            if not cantidad_txt.isdigit():
                continue

            cantidad = int(cantidad_txt)
            total = float(cols[6].get_text(strip=True).replace(",", ""))

            data.append({
                "producto": limpiar_producto(producto_raw),
                "tipo": normalizar(tipo_raw),
                "cantidad": cantidad,
                "total": total
            })

        except Exception as e:
            log(f"Error parseando fila: {e}")

    log(f"Items parseados: {len(data)}")
    return data



def get_platillo(nombre):
    return PLATILLOS.get(nombre)


def get_tipo(nombre):
    return TIPOS.get(nombre)


def crear_venta(cur, pv_id, turno_id, inicio, fin):
    cur.execute("""
        SELECT id FROM ventas
        WHERE punto_venta_id=%s
        AND turno_id=%s
        AND periodo_inicio=%s
        AND periodo_fin=%s
        LIMIT 1
    """, (pv_id, turno_id, inicio, fin))

    existente = cur.fetchone()

    if existente:
        return existente["id"], False

    cur.execute("""
        INSERT INTO ventas (punto_venta_id, turno_id, periodo_inicio, periodo_fin)
        VALUES (%s,%s,%s,%s)
    """, (pv_id, turno_id, inicio, fin))

    log("Venta creada")
    return cur.lastrowid, True


def limpiar_detalles(cur, venta_id):
    cur.execute("DELETE FROM ventas_platillo WHERE venta_id=%s", (venta_id,))
    cur.execute("DELETE FROM ventas_no_encontrados WHERE venta_id=%s", (venta_id,))
    cur.execute("DELETE FROM ventas_descuentos WHERE venta_id=%s", (venta_id,))


def insertar_batch(cur, venta_id, items, pv_id):

    agrupados = {}
    no_encontrados = []
    descuentos = []

    for item in items:

        platillo = get_platillo(item["producto"])
        tipo_id = get_tipo(item["tipo"])

        # DETECTAR DESCUENTO
        clave_desc = (item["producto"], pv_id)
        descuento_id = DESCUENTOS.get(clave_desc)

        if descuento_id:
            descuentos.append({
                "descuento_id": descuento_id,
                "monto": item["total"]
            })
            continue

        if not platillo or not tipo_id:
            no_encontrados.append(item)
            continue

        key = (platillo["id"], tipo_id)

        if key not in agrupados:
            agrupados[key] = {"cantidad": 0, "total": 0}

        agrupados[key]["cantidad"] += item["cantidad"]
        agrupados[key]["total"] += item["total"]

    # -------- INSERTAR PLATILLOS --------
    values = []

    for (platillo_id, tipo_id), data in agrupados.items():

        cantidad = data["cantidad"]
        total = data["total"]

        platillo = PLATILLOS_BY_ID[platillo_id]

        costo_unit = float(platillo["costo_manual"] or 0)
        costo_total = costo_unit * cantidad

        utilidad = total - costo_total
        margen = (utilidad / total * 100) if total else 0

        values.append((
            venta_id,
            platillo_id,
            tipo_id,
            cantidad,
            total,
            costo_total,
            utilidad,
            margen
        ))

    if values:
        cur.executemany("""
            INSERT INTO ventas_platillo (
                venta_id,
                platillo_id,
                tipo_producto_id,
                cantidad,
                total,
                costo_total,
                utilidad,
                margen
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, values)

        log(f" Insertados: {len(values)}")

    # -------- INSERTAR DESCUENTOS --------
    desc_values = []

    for d in descuentos:
        monto = float(d["monto"])
        monto = -abs(monto)

        desc_values.append((venta_id, d["descuento_id"], monto))

    if desc_values:
        cur.executemany("""
            INSERT INTO ventas_descuentos (
                venta_id,
                descuento_id,
                monto
            ) VALUES (%s,%s,%s)
        """, desc_values)

        log(f" Descuentos: {len(desc_values)}")

    # -------- NO ENCONTRADOS --------
    ne_values = []

    for item in no_encontrados:
        ne_values.append((
            venta_id,
            item["producto"],
            None,
            item["cantidad"],
            item["total"],
            0,
            item["total"],
            100 if item["total"] else 0
        ))

    if ne_values:
        cur.executemany("""
            INSERT INTO ventas_no_encontrados (
                venta_id,
                producto_nombre,
                tipo_producto_id,
                cantidad,
                total,
                costo_total,
                utilidad,
                margen
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, ne_values)

        log(f" No encontrados: {len(ne_values)}")


def actualizar_totales_venta(cur, venta_id):
    """Actualiza totales de una venta incluyendo platillos, no encontrados y descuentos."""
    
    cur.execute("""
        UPDATE ventas v
        LEFT JOIN (
            SELECT venta_id,
                SUM(total) AS total_platillos,
                SUM(costo_total) AS costo_platillos
            FROM ventas_platillo
            GROUP BY venta_id
        ) vp ON vp.venta_id = v.id
        LEFT JOIN (
            SELECT venta_id,
                SUM(total) AS total_no_encontrados,
                SUM(costo_total) AS costo_no_encontrados
            FROM ventas_no_encontrados
            GROUP BY venta_id
        ) vne ON vne.venta_id = v.id
        LEFT JOIN (
            SELECT venta_id,
                SUM(monto) AS total_descuento
            FROM ventas_descuentos
            GROUP BY venta_id
        ) vd ON vd.venta_id = v.id
        SET 
            -- Calcular subtotal (suma de ventas sin descuentos)
            v.subtotal = COALESCE(vp.total_platillos, 0) + COALESCE(vne.total_no_encontrados, 0),
            
            -- Calcular costo total
            v.costo_total = COALESCE(vp.costo_platillos, 0) + COALESCE(vne.costo_no_encontrados, 0),
            
            -- Monto total de descuentos (ya debe ser negativo en la tabla)
            v.descuento = COALESCE(vd.total_descuento, 0),
            
            -- Total final = ventas + descuentos (donde descuentos son negativos)
            v.total = COALESCE(vp.total_platillos, 0) + COALESCE(vne.total_no_encontrados, 0) + COALESCE(vd.total_descuento, 0),
            
            -- Utilidad = total final - costo total
            v.utilidad = (COALESCE(vp.total_platillos, 0) + COALESCE(vne.total_no_encontrados, 0) + COALESCE(vd.total_descuento, 0)) 
                       - (COALESCE(vp.costo_platillos, 0) + COALESCE(vne.costo_no_encontrados, 0)),
            
            -- Margen = (utilidad / total) * 100
            v.margen = CASE 
                WHEN (COALESCE(vp.total_platillos, 0) + COALESCE(vne.total_no_encontrados, 0) + COALESCE(vd.total_descuento, 0)) > 0 
                THEN ((COALESCE(vp.total_platillos, 0) + COALESCE(vne.total_no_encontrados, 0) + COALESCE(vd.total_descuento, 0)) 
                      - (COALESCE(vp.costo_platillos, 0) + COALESCE(vne.costo_no_encontrados, 0))) 
                     / (COALESCE(vp.total_platillos, 0) + COALESCE(vne.total_no_encontrados, 0) + COALESCE(vd.total_descuento, 0)) * 100
                ELSE 0 
            END
        WHERE v.id = %s
    """, (venta_id,))
    
    # Verificar que la actualización fue correcta
    cur.execute("""
        SELECT subtotal, descuento, total, costo_total, utilidad, margen 
        FROM ventas WHERE id = %s
    """, (venta_id,))
    
    result = cur.fetchone()
    log(f"Venta {venta_id}: subtotal={result['subtotal']}, descuento={result['descuento']}, "
        f"total={result['total']}, costo={result['costo_total']}, utilidad={result['utilidad']}, margen={result['margen']:.2f}%")


def reset_horas(page):
    page.evaluate("""
        document.querySelectorAll('input[name^="frHora"]').forEach(el => el.checked = false);
    """)


def set_horas(page, turno_id):
    reset_horas(page)

    for h in TURNOS_HORAS[turno_id]:
        selector = f'input[name="frHora{h}"]'
        locator = page.locator(selector)

        try:
            locator.wait_for(state="attached", timeout=5000)
            if not locator.is_checked():
                locator.click(force=True)
        except:
            pass


def reset_tipo_producto(page):
    try:
        checkbox = page.locator('input[name="frTipoProducto22"]')
        checkbox.wait_for(state="attached", timeout=5000)

        if checkbox.is_checked():
            checkbox.uncheck(force=True)

    except:
        pass


MAX_REINTENTOS = 5
ESPERA_REINTENTO_MS = 120_000  # 2 minutos


def scrape_turno(page, pv_nombre, turno_id, periodo_ini, periodo_fin):
    """Navega desde cero y hace el scraping para un PV y turno específico."""
    page.goto(REP_URL)
    page.select_option('select[name="frArea[]"]', label=pv_nombre)
    page.fill("#frInicio", periodo_ini)
    page.fill("#frFinal", periodo_fin)
    page.select_option('select[name="frReporte"]', "totales")
    set_horas(page, turno_id)
    reset_tipo_producto(page)
    page.click('button[name="frBoton"]')
    esperar_carga_completa(page)
    return parsear(page.content())


def scrape_con_reintentos(page, pv_nombre, turno_id, periodo_ini, periodo_fin):
    """Intenta el scraping hasta MAX_REINTENTOS veces. En cada fallo refresca y espera."""
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            items = scrape_turno(page, pv_nombre, turno_id, periodo_ini, periodo_fin)
            if intento > 1:
                log(f"Recuperado en intento {intento}/{MAX_REINTENTOS}")
            return items
        except Exception as e:
            log(f"[FALLO {intento}/{MAX_REINTENTOS}] {e}")
            if intento < MAX_REINTENTOS:
                log(f"Esperando {ESPERA_REINTENTO_MS // 1000}s antes de reintentar...")
                page.wait_for_timeout(ESPERA_REINTENTO_MS)
                try:
                    page.reload()
                    page.wait_for_load_state("networkidle")
                except Exception:
                    pass

    log(f"[ERROR] Se agotaron los {MAX_REINTENTOS} reintentos. Se omite PV='{pv_nombre}' turno={turno_id}.")
    return []


def worker_turno(turno_id, periodos, pvs):
    """Worker independiente: su propio browser y conexión a BD para un turno."""
    tag = f"[T{turno_id}]"
    conn_local, cur = make_cursor()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()

            log(f"{tag} Login...")
            page.goto(LOGIN_URL)
            page.fill('input[name="frUsuario"]', USER)
            page.fill('input[name="frContrasena"]', PASSWORD)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")
            log(f"{tag} Login OK")

            for periodo_ini, periodo_fin in periodos:
                log(f"{tag} === Periodo: {periodo_ini} → {periodo_fin} ===")

                d, m, y = periodo_ini.split('/')
                df, mf, yf = periodo_fin.split('/')
                inicio_db = f"{y}-{m}-{d} 00:00:00"
                fin_db = f"{yf}-{mf}-{df} 23:59:59"

                for pv in pvs:
                    log(f"{tag} PV: {pv['nombre']}")

                    items = scrape_con_reintentos(page, pv["nombre"], turno_id, periodo_ini, periodo_fin)

                    venta_id, es_nueva = crear_venta(cur, pv["id"], turno_id, inicio_db, fin_db)

                    if not es_nueva:
                        log(f"{tag} Reprocesando venta")
                        limpiar_detalles(cur, venta_id)

                    insertar_batch(cur, venta_id, items, pv["id"])
                    actualizar_totales_venta(cur, venta_id)

            log(f"{tag} Proceso terminado")
            browser.close()

    finally:
        cur.close()
        conn_local.close()


def main():

    cargar_catalogos()

    periodos = generar_periodos_mensuales(FECHA_INI, FECHA_FIN)
    log(f"Períodos mensuales a procesar: {len(periodos)}")
    for p_ini, p_fin in periodos:
        log(f"  → {p_ini} / {p_fin}")

    cursor.execute("SELECT id, nombre FROM puntos_venta WHERE status=1")
    pvs = cursor.fetchall()

    threads = [
        threading.Thread(target=worker_turno, args=(1, periodos, pvs), name="Turno-1"),
        threading.Thread(target=worker_turno, args=(2, periodos, pvs), name="Turno-2"),
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    log("Pipeline completado")


if __name__ == "__main__":
    main()
