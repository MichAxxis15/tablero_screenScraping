import os
import re
import unicodedata
import pymysql
from bs4 import BeautifulSoup
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


def log(msg):
    print(f"[LOG] {msg}")



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



def esperar_tabla(page):
    try:
        page.wait_for_function("""
            () => {
                const rows = document.querySelectorAll("table tr");
                return Array.from(rows).some(r => {
                    const tds = r.querySelectorAll("td");
                    return tds.length === 14 && !isNaN(parseInt(tds[3]?.innerText));
                });
            }
        """, timeout=20000)
    except:
        log("Tabla sin datos suficientes")


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


def crear_venta(pv_id, turno_id, inicio, fin):
    cursor.execute("""
        SELECT id FROM ventas
        WHERE punto_venta_id=%s
        AND turno_id=%s
        AND periodo_inicio=%s
        AND periodo_fin=%s
        LIMIT 1
    """, (pv_id, turno_id, inicio, fin))

    existente = cursor.fetchone()

    if existente:
        return existente["id"], False

    cursor.execute("""
        INSERT INTO ventas (punto_venta_id, turno_id, periodo_inicio, periodo_fin)
        VALUES (%s,%s,%s,%s)
    """, (pv_id, turno_id, inicio, fin))

    log("Venta creada")
    return cursor.lastrowid, True


def limpiar_detalles(venta_id):
    cursor.execute("DELETE FROM ventas_platillo WHERE venta_id=%s", (venta_id,))
    cursor.execute("DELETE FROM ventas_no_encontrados WHERE venta_id=%s", (venta_id,))
    cursor.execute("DELETE FROM ventas_descuentos WHERE venta_id=%s", (venta_id,))


def insertar_batch(venta_id, items, pv_id):

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
        cursor.executemany("""
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
        cursor.executemany("""
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
        cursor.executemany("""
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


def actualizar_totales_venta(venta_id):

    cursor.execute("""
        UPDATE ventas v

        LEFT JOIN (
            SELECT venta_id,
                   SUM(total) total,
                   SUM(costo_total) costo_total
            FROM ventas_platillo
            GROUP BY venta_id
        ) x ON x.venta_id = v.id

        LEFT JOIN (
            SELECT venta_id,
                   SUM(monto) total_descuento
            FROM ventas_descuentos
            GROUP BY venta_id
        ) d ON d.venta_id = v.id

        SET 
            v.subtotal = COALESCE(x.total, 0),
            v.costo_total = COALESCE(x.costo_total, 0),
            v.descuento = COALESCE(d.total_descuento, 0),
            v.total = COALESCE(x.total, 0) + COALESCE(d.total_descuento, 0),
            v.utilidad = (COALESCE(x.total, 0) + COALESCE(d.total_descuento, 0)) - COALESCE(x.costo_total, 0),
            v.margen = CASE 
                WHEN (COALESCE(x.total, 0) + COALESCE(d.total_descuento, 0)) > 0 
                THEN ((COALESCE(x.total, 0) + COALESCE(d.total_descuento, 0)) - COALESCE(x.costo_total, 0)) 
                     / (COALESCE(x.total, 0) + COALESCE(d.total_descuento, 0)) * 100
                ELSE 0
            END

        WHERE v.id = %s
    """, (venta_id,))


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


def main():

    cargar_catalogos()

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        log("Login...")
        page.goto(LOGIN_URL)
        page.fill('input[name="frUsuario"]', USER)
        page.fill('input[name="frContrasena"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        log("Login OK")

        cursor.execute("SELECT id, nombre FROM puntos_venta WHERE status=1")
        pvs = cursor.fetchall()

        for pv in pvs:

            log(f"PV: {pv['nombre']}")

            page.goto(REP_URL)

            page.select_option('select[name="frArea[]"]', label=pv["nombre"])

            d,m,y = FECHA_INI.split('/')
            df,mf,yf = FECHA_FIN.split('/')

            inicio_db = f"{y}-{m}-{d} 00:00:00"
            fin_db = f"{yf}-{mf}-{df} 23:59:59"

            page.fill("#frInicio", FECHA_INI)
            page.fill("#frFinal", FECHA_FIN)
            page.select_option('select[name="frReporte"]', "totales")

            for turno_id in [1, 2]:

                log(f"Procesando turno {turno_id}...")

                set_horas(page, turno_id)
                reset_tipo_producto(page)

                page.click('button[name="frBoton"]')
                esperar_tabla(page)

                page.wait_for_timeout(60000)

                items = parsear(page.content())

                venta_id, es_nueva = crear_venta(pv["id"], turno_id, inicio_db, fin_db)

                if not es_nueva:
                    log("Reprocesando venta")
                    limpiar_detalles(venta_id)

                insertar_batch(venta_id, items, pv["id"])
                actualizar_totales_venta(venta_id)

        log("Proceso terminado")
        browser.close()


if __name__ == "__main__":
    main()
