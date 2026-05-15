import pandas as pd
import pymysql
import os
import math
import logging
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "cursorclass": pymysql.cursors.DictCursor
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_PATH = os.path.join(BASE_DIR, "recetas", "recetas.xlsx")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# ---------------- LIMPIEZA ----------------

def limpiar_nan(valor):
    if valor is None:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    return valor

def limpiar_texto(texto):
    texto = limpiar_nan(texto)
    return str(texto).strip().lower() if texto else None

def limpiar_numero(valor):
    valor = limpiar_nan(valor)
    try:
        return float(valor) if valor is not None else 0
    except:
        return 0

def obtener_entero(valor):
    valor = limpiar_nan(valor)
    try:
        return int(valor) if valor is not None else None
    except:
        return None

def aplicar_merma(cantidad, merma):
    merma = limpiar_numero(merma)
    return cantidad * (1 + merma / 100)

# ---------------- UNIDADES ----------------

def normalizar_unidad(u):
    u = limpiar_texto(u)
    mapa = {
        "ml": "ml", "mililitro": "ml", "mililitros": "ml",
        "lt": "lt", "l": "lt", "litro": "lt", "litros": "lt",
        "gr": "gr", "g": "gr", "gramo": "gr",
        "kg": "kg",
        "pz": "pz", "pieza": "pz", "pza": "pz", "und": "pz"
    }
    return mapa.get(u, u)

def convertir_a_base(cantidad, unidad):
    unidad = normalizar_unidad(unidad)

    if unidad == "ml":
        return cantidad / 1000, "lt"
    elif unidad == "gr":
        return cantidad / 1000, "kg"
    return cantidad, unidad

def obtener_unidad_id(cursor, cache, unidad):
    unidad = normalizar_unidad(unidad)

    if not unidad:
        return None

    unidad_id = cache.get(unidad)
    if unidad_id:
        return unidad_id

    cursor.execute("SELECT id FROM unidades_medida WHERE clave=%s", (unidad,))
    result = cursor.fetchone()

    if result:
        cache[unidad] = result["id"]
        return result["id"]

    logging.error(f"Unidad no encontrada: {unidad}")
    return None

# ---------------- VALIDACIONES ----------------

def validar_columnas(df, requeridas):
    cols = [c.strip().lower() for c in df.columns]
    for r in requeridas:
        if r not in cols:
            raise Exception(f"Falta columna requerida: {r}")

def preparar_dataframe(df):
    df.columns = [c.strip().lower() for c in df.columns]
    df[:] = df.where(pd.notnull(df), None)
    return df

# ---------------- CACHE ----------------

def cargar_cache(cursor):
    logging.info("Cargando cache...")

    cursor.execute("SELECT id, nombre FROM categorias_producto")
    categorias = {limpiar_texto(r["nombre"]): r["id"] for r in cursor.fetchall()}

    cursor.execute("SELECT id, numero_articulo FROM articulos")
    articulos = {r["numero_articulo"]: r for r in cursor.fetchall()}

    cursor.execute("SELECT id, nombre FROM subrecetas")
    subrecetas = {limpiar_texto(r["nombre"]): r["id"] for r in cursor.fetchall()}

    cursor.execute("SELECT id, clave FROM unidades_medida")
    unidades = {limpiar_texto(r["clave"]): r["id"] for r in cursor.fetchall()}

    return categorias, articulos, subrecetas, unidades

# ---------------- SUBRECETAS ----------------

def obtener_subreceta_id(cursor, cache, nombre):
    nombre = limpiar_texto(nombre)
    if not nombre:
        return None

    sub_id = cache.get(nombre)
    if sub_id:
        return sub_id

    cursor.execute("SELECT id FROM subrecetas WHERE nombre=%s", (nombre,))
    result = cursor.fetchone()

    if result:
        cache[nombre] = result["id"]
        return result["id"]

    logging.error(f"Subreceta no existe: {nombre}")
    return None

def crear_subrecetas(cursor, df, unidades_cache):
    logging.info("Creando subrecetas...")

    for _, row in df.iterrows():
        nombre = limpiar_texto(row.get("producto"))
        unidad = row.get("u.medida")

        if not nombre:
            continue

        unidad_id = obtener_unidad_id(cursor, unidades_cache, unidad)

        if not unidad_id:
            continue

        cursor.execute("""
            INSERT INTO subrecetas(nombre, rendimiento, unidad_medida_id)
            VALUES (%s, 1, %s)
            ON DUPLICATE KEY UPDATE unidad_medida_id=VALUES(unidad_medida_id)
        """, (nombre, unidad_id))

def cargar_componentes_subrecetas(cursor, df, articulos_cache, subrecetas_cache):

    actual = None
    sub_id = None

    for _, row in df.iterrows():

        nombre = limpiar_texto(row.get("producto"))
        if not nombre:
            continue

        if nombre != actual:
            actual = nombre
            sub_id = obtener_subreceta_id(cursor, subrecetas_cache, nombre)

            if not sub_id:
                continue

            cursor.execute("DELETE FROM subreceta_componentes WHERE subreceta_padre_id=%s", (sub_id,))
            logging.info(f"Subreceta: {nombre}")

        cantidad = limpiar_numero(row.get("cantidad"))
        merma = row.get("merma")

        cantidad = aplicar_merma(cantidad, merma)
        cantidad, _ = convertir_a_base(cantidad, row.get("u.medida"))

        articulo_id = None
        subreceta_id = None

        numero = obtener_entero(row.get("artículo"))
        nombre_ing = limpiar_texto(row.get("ingrediente"))

        if numero is not None:
            art = articulos_cache.get(numero)
            if art:
                articulo_id = art["id"]
            else:
                logging.error(f"Artículo no encontrado: {numero}")

        elif nombre_ing:
            subreceta_id = obtener_subreceta_id(cursor, subrecetas_cache, nombre_ing)

        if not articulo_id and not subreceta_id:
            continue

        cursor.execute("""
            INSERT INTO subreceta_componentes
            (subreceta_padre_id, articulo_id, subreceta_id, cantidad)
            VALUES (%s,%s,%s,%s)
        """, (sub_id, articulo_id, subreceta_id, cantidad))

# ---------------- PRODUCTOS ----------------

def procesar_productos(cursor, df, categorias_cache, articulos_cache, subrecetas_cache, tipo=""):

    df["producto"] = df["producto"].ffill()

    actual = None
    producto_id = None

    for _, row in df.iterrows():

        nombre = limpiar_texto(row.get("producto"))
        if not nombre:
            continue

        if nombre != actual:
            actual = nombre

            grupo = limpiar_texto(row.get("grupo"))
            categoria_id = categorias_cache.get(grupo)

            if not categoria_id:
                logging.warning(f"[{tipo}] Categoría no encontrada: {grupo}")
                continue

            cursor.execute("""
                INSERT INTO platillos(nombre, categoria_id)
                VALUES (%s,%s)
                ON DUPLICATE KEY UPDATE categoria_id=VALUES(categoria_id)
            """, (nombre, categoria_id))

            cursor.execute("SELECT id FROM platillos WHERE nombre=%s", (nombre,))
            producto_id = cursor.fetchone()["id"]

            cursor.execute("DELETE FROM platillo_componentes WHERE platillo_id=%s", (producto_id,))
            logging.info(f"{tipo}: {nombre}")

        cantidad = limpiar_numero(row.get("cantidad"))
        merma = row.get("merma")

        cantidad = aplicar_merma(cantidad, merma)
        cantidad, _ = convertir_a_base(cantidad, row.get("u.medida"))

        articulo_id = None
        subreceta_id = None

        numero = obtener_entero(row.get("artículo"))
        nombre_ing = limpiar_texto(row.get("ingrediente"))

        if numero is not None:
            art = articulos_cache.get(numero)
            if art:
                articulo_id = art["id"]
            else:
                logging.error(f"Artículo no encontrado: {numero}")

        elif nombre_ing:
            subreceta_id = obtener_subreceta_id(cursor, subrecetas_cache, nombre_ing)

        if not articulo_id and not subreceta_id:
            continue

        cursor.execute("""
            INSERT INTO platillo_componentes
            (platillo_id, articulo_id, subreceta_id, cantidad)
            VALUES (%s,%s,%s,%s)
        """, (producto_id, articulo_id, subreceta_id, cantidad))

# ---------------- MAIN ----------------

def main():

    if not os.path.exists(EXCEL_PATH):
        raise FileNotFoundError(EXCEL_PATH)

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    conn.autocommit(False)

    try:
        logging.info("Leyendo Excel...")

        df_sub = preparar_dataframe(pd.read_excel(EXCEL_PATH, sheet_name="Sub"))
        df_plat = preparar_dataframe(pd.read_excel(EXCEL_PATH, sheet_name="Platillos"))
        df_beb = preparar_dataframe(pd.read_excel(EXCEL_PATH, sheet_name="Bebidas"))

        validar_columnas(df_sub, ["producto", "cantidad"])
        validar_columnas(df_plat, ["producto", "grupo", "cantidad"])
        validar_columnas(df_beb, ["producto", "grupo", "cantidad"])

        categorias_cache, articulos_cache, subrecetas_cache, unidades_cache = cargar_cache(cursor)

        # SUBRECETAS
        crear_subrecetas(cursor, df_sub, unidades_cache)
        _, _, subrecetas_cache, _ = cargar_cache(cursor)

        cargar_componentes_subrecetas(cursor, df_sub, articulos_cache, subrecetas_cache)

        # PRODUCTOS
        procesar_productos(cursor, df_plat, categorias_cache, articulos_cache, subrecetas_cache, "PLATILLO")
        procesar_productos(cursor, df_beb, categorias_cache, articulos_cache, subrecetas_cache, "BEBIDA")

        conn.commit()
        logging.info("✅ COMPLETADO")

    except Exception as e:
        conn.rollback()
        logging.error(f"❌ ERROR: {str(e)}")

    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()