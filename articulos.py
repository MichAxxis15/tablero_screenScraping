from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import pandas as pd
import pymysql
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=".env")

LOGIN_URL = os.getenv("LOGIN_URL")
USER = os.getenv("DATUM_USER")
PASSWORD = os.getenv("DATUM_PASSWORD")
REP_EXIS_URL = os.getenv("REP_EXIS_URL")

carpeta = os.path.join("articulos")
os.makedirs(carpeta, exist_ok=True)

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "autocommit": True
}

MESES = {
    "Ene": "01","Feb": "02","Mar": "03","Abr": "04","May": "05","Jun": "06",
    "Jul": "07","Ago": "08","Sep": "09","Oct": "10","Nov": "11","Dic": "12"
}


def normalizar(txt):
    return txt.strip().upper() if txt else None

def convertir_fecha(fecha_txt):
    if not fecha_txt:
        return None
    partes = fecha_txt.split()
    if len(partes) != 3:
        return None
    dia, mes_txt, año = partes
    mes = MESES.get(mes_txt, "01")
    return f"20{año}-{mes}-{dia.zfill(2)}"

def parsear_medida(txt):
    if not txt:
        return None, None

    txt = txt.replace(",", "").strip().lower()
    partes = txt.split()

    if len(partes) >= 2:
        try:
            contenido = float(partes[0])
        except:
            contenido = None

        unidad = partes[-1]
        return contenido, unidad

    return None, None

MAP_UNIDADES = {
    "kg": "kg", "kgs": "kg",
    "lt": "lt", "lts": "lt",
    "pz": "pz", "pza": "pz", "pzas": "pz",
    "gr": "gr", "g": "gr",
    "ml": "ml"
}

def normalizar_unidad(unidad):
    if not unidad:
        return None
    unidad = unidad.strip().lower()
    return MAP_UNIDADES.get(unidad, unidad)

def conexion():
    return pymysql.connect(**DB_CONFIG)


def cargar_catalogos(cursor):
    cursor.execute("SELECT id, nombre FROM lineas")
    lineas = {nombre.strip().upper(): id for id, nombre in cursor.fetchall()}

    cursor.execute("SELECT id, nombre, linea_id FROM familias")
    familias = {}
    for id_, nombre, linea_id in cursor.fetchall():
        familias[(nombre.strip().upper(), linea_id)] = id_

    cursor.execute("SELECT id, clave FROM unidades_medida")
    unidades = {clave.strip().lower(): id for id, clave in cursor.fetchall()}

    return lineas, familias, unidades


def guardar_articulos(conn, articulos):
    cursor = conn.cursor()

    lineas_dict, familias_dict, unidades_dict = cargar_catalogos(cursor)

    valores = []
    errores = []

    for art in articulos:
        linea = normalizar(art["linea"])
        familia = normalizar(art["familia"])

        contenido, unidad_raw = parsear_medida(art["medida"])
        unidad = normalizar_unidad(unidad_raw)

        linea_id = lineas_dict.get(linea)

        if not linea_id:
            errores.append(f"Línea no existe: {linea}")
            continue

        familia_id = familias_dict.get((familia, linea_id))

        if not familia_id:
            errores.append(f"Artículo {art['numero_articulo']} → Familia no existe: {familia} (Línea: {linea})")
            continue

        unidad_id = unidades_dict.get(unidad)

        if not unidad_id:
            errores.append(f"Artículo {art['numero_articulo']} → Unidad no existe: {art['medida']}")
            continue

        try:
            numero = int(art["numero_articulo"])
        except:
            continue

        valores.append((
            familia_id,
            numero,
            art["descripcion"],
            art["ultimo_mov"],
            unidad_id,
            contenido,
            art["ultimo_costo_compra"]
        ))

    sql = """
        INSERT INTO articulos
        (familia_id, numero_articulo, descripcion, ultimo_mov, unidad_medida_id, contenido, costo_unitario)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            familia_id = VALUES(familia_id),
            descripcion = VALUES(descripcion),
            ultimo_mov = VALUES(ultimo_mov),
            unidad_medida_id = VALUES(unidad_medida_id),
            contenido = VALUES(contenido),
            costo_unitario = VALUES(costo_unitario);
    """

    cursor.executemany(sql, valores)

    print(f"{len(valores)} artículos insertados/actualizados")

    if errores:
        print("\nERRORES DETECTADOS:")
        for e in errores[:10]:
            print("-", e)


def extraer_articulos(html):
    soup = BeautifulSoup(html, "html.parser")
    filas = soup.find_all("tr")

    datos = []
    linea_actual = None
    familia_actual = None

    for tr in filas:
        tds = tr.find_all("td")

        if len(tds) == 1 and tds[0].find("strong") and not tds[0].find("strong").get("style"):
            linea_actual = tds[0].text.strip()
            continue

        if len(tds) == 1 and "padding-left:10px" in str(tr):
            familia_actual = tds[0].text.strip()
            continue

        if len(tds) >= 12:
            numero = tds[1].text.strip()
            if not numero.isdigit():
                continue

            try:
                datos.append({
                    "linea": linea_actual,
                    "familia": familia_actual,
                    "numero_articulo": numero,
                    "descripcion": tds[2].text.strip(),
                    "ultimo_mov": convertir_fecha(tds[4].text.strip()),
                    "medida": tds[6].text.strip(),
                    "ultimo_costo_compra": float(tds[7].text.strip().replace(",", "") or 0)
                })
            except:
                continue

    return datos


def main():
    conn = conexion()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            print("Login")
            page.goto(LOGIN_URL)
            page.fill('input[name="frUsuario"]', USER)
            page.fill('input[name="frContrasena"]', PASSWORD)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")

            print("Cargando datos...")
            page.goto(REP_EXIS_URL)
            page.wait_for_load_state("networkidle")

            #page.select_option('#frAlmacen', "1")
            #page.select_option('select[name="frLinea"]', "1")
            page.click('button[value="Buscar"]')
            page.wait_for_load_state("networkidle", timeout=100000)
            
            html = page.content()
            articulos = extraer_articulos(html)

            print(f"Extraídos: {len(articulos)}")

            df = pd.DataFrame(articulos)

            ruta = os.path.join(
                carpeta,
                f"articulos_{datetime.now().strftime('%H%M%S')}.xlsx"
            )

            df.to_excel(ruta, index=False)

            print(f"Archivo guardado en: {ruta}")

            guardar_articulos(conn, articulos)

        finally:
            browser.close()

if __name__ == "__main__":
    main()
