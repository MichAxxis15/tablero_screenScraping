import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, RealDictCursor

load_dotenv("config.env")

FECHA_INI = os.getenv("FECHA_INICIO")
FECHA_FIN = os.getenv("FECHA_FIN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTE_DIR = os.path.join(BASE_DIR, "reporte datum")
EXCEL_PATH = os.getenv("EXCEL_PATH")

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "dbname": os.getenv("DB_NAME"),
}

TURNOS = {
    1: {"nombre": "Mañana", "inicio": "07:00:00", "fin": "13:59:00"},
    2: {"nombre": "Tarde/Noche", "inicio": "14:00:00", "fin": "03:00:00"},
}

PLATILLOS = {}
TIPOS = {}
PUNTOS_VENTA = {}
DESCUENTOS = {}


def log(msg):
    print(f"[LOG] {msg}")


def make_connection():
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO datum_inter")
    return conn


def normalizar(texto):
    if texto is None or pd.isna(texto):
        return None
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto or None


def normalizar_columna(texto):
    texto = normalizar(texto)
    return texto.replace(" ", "_") if texto else ""


def limpiar_producto(texto):
    texto = normalizar(texto)
    return texto.replace("+", "").strip() if texto else None


def limpiar_numero(valor, default=0):
    if valor is None or pd.isna(valor):
        return default
    if isinstance(valor, str):
        valor = valor.replace("$", "").replace(",", "").strip()
    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def parsear_fecha(valor):
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, datetime):
        return valor
    fecha = pd.to_datetime(valor, dayfirst=True, errors="coerce")
    return None if pd.isna(fecha) else fecha.to_pydatetime()


def parsear_fecha_config(valor):
    if not valor or not valor.strip():
        return None
    fecha = pd.to_datetime(valor.strip(), dayfirst=True, errors="coerce")
    return None if pd.isna(fecha) else fecha.date()


def detectar_turno(fecha):
    hora = fecha.hour
    if 7 <= hora <= 13:
        return 1
    if hora >= 14 or hora <= 3:
        return 2
    return None


def encontrar_reporte_excel():
    if EXCEL_PATH:
        path = EXCEL_PATH.strip()
        if not os.path.isabs(path):
            path = os.path.join(BASE_DIR, path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"No se encontró el archivo configurado en EXCEL_PATH: {path}")
        return path

    archivos = [
        os.path.join(REPORTE_DIR, nombre)
        for nombre in os.listdir(REPORTE_DIR)
        if nombre.lower().endswith((".xlsx", ".xls")) and not nombre.startswith("~$")
    ]
    if not archivos:
        raise FileNotFoundError(f"No se encontró un archivo Excel en {REPORTE_DIR}")
    return max(archivos, key=os.path.getmtime)


def cargar_catalogos(cur):
    global PLATILLOS, TIPOS, PUNTOS_VENTA, DESCUENTOS

    cur.execute("SELECT id, nombre, costo_manual FROM platillos WHERE status = 1")
    PLATILLOS = {normalizar(row["nombre"]): row for row in cur.fetchall()}

    cur.execute("SELECT id, nombre, punto_venta_id FROM tipos_producto WHERE status = 1")
    TIPOS = {normalizar(row["nombre"]): row for row in cur.fetchall()}

    cur.execute("SELECT id, nombre FROM puntos_venta WHERE status = 1")
    PUNTOS_VENTA = {normalizar(row["nombre"]): row for row in cur.fetchall()}

    cur.execute("""
        SELECT id, nombre, punto_venta_id, tipo_producto_id
        FROM descuentos
        WHERE status = 1
    """)
    DESCUENTOS = {}
    for row in cur.fetchall():
        DESCUENTOS[(normalizar(row["nombre"]), row["punto_venta_id"])] = row

    log(f"Platillos: {len(PLATILLOS)}")
    log(f"Tipos producto: {len(TIPOS)}")
    log(f"Puntos venta: {len(PUNTOS_VENTA)}")
    log(f"Descuentos: {len(DESCUENTOS)}")


def buscar_punto_venta(nombre_hoja):
    hoja = normalizar(nombre_hoja)
    if hoja in PUNTOS_VENTA:
        return PUNTOS_VENTA[hoja]

    for nombre, punto_venta in PUNTOS_VENTA.items():
        if nombre in hoja or hoja in nombre:
            return punto_venta

    return None


def leer_reporte_excel(path):
    hojas = pd.read_excel(path, sheet_name=None)
    fecha_ini = parsear_fecha_config(FECHA_INI)
    fecha_fin = parsear_fecha_config(FECHA_FIN)
    columnas_requeridas = {"producto", "tipo", "cantidad", "total_ventas", "fecha"}
    registros = []

    for nombre_hoja, df in hojas.items():
        total_hoja = 0
        punto_venta = buscar_punto_venta(nombre_hoja)
        if not punto_venta:
            log(f"Hoja omitida, no coincide con punto de venta: {nombre_hoja}")
            continue

        if df.empty:
            continue

        df = df.copy()
        df.columns = [normalizar_columna(col) for col in df.columns]
        faltantes = columnas_requeridas - set(df.columns)
        if faltantes:
            log(f"Hoja '{nombre_hoja}' omitida. Faltan columnas: {', '.join(sorted(faltantes))}")
            continue

        for _, row in df.iterrows():
            fecha = parsear_fecha(row.get("fecha"))
            if not fecha:
                continue

            fecha_dia = fecha.date()
            if fecha_ini and fecha_dia < fecha_ini:
                continue
            if fecha_fin and fecha_dia > fecha_fin:
                continue

            turno_id = detectar_turno(fecha)
            if not turno_id:
                continue

            producto = limpiar_producto(row.get("producto"))
            tipo = normalizar(row.get("tipo"))
            cantidad = int(limpiar_numero(row.get("cantidad")))
            total = limpiar_numero(row.get("total_ventas"))

            if not producto or cantidad <= 0:
                continue

            registros.append({
                "punto_venta_origen_id": punto_venta["id"],
                "punto_venta_origen": punto_venta["nombre"],
                "fecha": fecha_dia,
                "turno_id": turno_id,
                "producto": producto,
                "tipo": tipo,
                "cantidad": cantidad,
                "total": total,
            })
            total_hoja += 1

        log(f"Hoja '{nombre_hoja}': {total_hoja} registros válidos")

    return registros


def es_descuento(item, tipo):
    if item["producto"].startswith("descuento"):
        return True
    return bool(tipo and normalizar(tipo["nombre"]) == "descuentos")


def resolver_punto_venta_real(item, tipo, descuento=False):
    if descuento:
        return item["punto_venta_origen_id"]
    if tipo and tipo.get("punto_venta_id"):
        return tipo["punto_venta_id"]
    return item["punto_venta_origen_id"]


def buscar_descuento(item, punto_venta_id, tipo):
    descuento = DESCUENTOS.get((item["producto"], punto_venta_id))
    if descuento:
        return descuento

    candidatos = [
        row for (nombre, pv_id), row in DESCUENTOS.items()
        if pv_id == punto_venta_id and (nombre in item["producto"] or item["producto"] in nombre)
    ]
    if candidatos:
        return candidatos[0]

    if tipo and tipo.get("id"):
        for row in DESCUENTOS.values():
            if row["punto_venta_id"] == punto_venta_id and row["tipo_producto_id"] == tipo["id"]:
                return row

    return None


def clasificar_item(item):
    tipo = TIPOS.get(item["tipo"])
    descuento = es_descuento(item, tipo)
    punto_venta_id = resolver_punto_venta_real(item, tipo, descuento=descuento)

    if descuento:
        descuento_row = buscar_descuento(item, punto_venta_id, tipo)
        return punto_venta_id, {
            "clase": "descuento",
            "descuento_id": descuento_row["id"] if descuento_row else None,
            "nombre": item["producto"],
            "tipo_producto_id": tipo["id"] if tipo else None,
            "monto": -abs(item["total"]),
        }

    platillo = PLATILLOS.get(item["producto"])
    if not platillo or not tipo:
        return punto_venta_id, {
            "clase": "no_encontrado",
            "nombre": item["producto"],
            "tipo_producto_id": tipo["id"] if tipo else None,
            "cantidad": item["cantidad"],
            "total": item["total"],
            "costo_total": 0,
            "utilidad": item["total"],
            "margen": 100 if item["total"] else 0,
        }

    costo_unitario = float(platillo["costo_manual"] or 0)
    costo_total = costo_unitario * item["cantidad"]
    utilidad = item["total"] - costo_total
    margen = (utilidad / item["total"] * 100) if item["total"] else 0

    return punto_venta_id, {
        "clase": "encontrado",
        "platillo_id": platillo["id"],
        "nombre": item["producto"],
        "tipo_producto_id": tipo["id"],
        "cantidad": item["cantidad"],
        "precio_unitario": item["total"] / item["cantidad"] if item["cantidad"] else 0,
        "total": item["total"],
        "costo_unitario": costo_unitario,
        "costo_total": costo_total,
        "utilidad": utilidad,
        "margen": margen,
    }


def agregar_item(agregado, item):
    if item["clase"] == "encontrado":
        key = (item["platillo_id"], item["tipo_producto_id"])
        target = agregado["encontrados"].setdefault(key, {**item})
        if target is not item:
            target["cantidad"] += item["cantidad"]
            target["total"] += item["total"]
            target["costo_total"] += item["costo_total"]
            target["utilidad"] = target["total"] - target["costo_total"]
            target["precio_unitario"] = target["total"] / target["cantidad"] if target["cantidad"] else 0
            target["margen"] = (target["utilidad"] / target["total"] * 100) if target["total"] else 0
        return

    if item["clase"] == "no_encontrado":
        key = (item["nombre"], item["tipo_producto_id"])
        target = agregado["no_encontrados"].setdefault(key, {**item})
        if target is not item:
            target["cantidad"] += item["cantidad"]
            target["total"] += item["total"]
            target["utilidad"] = target["total"]
        return

    key = (item["descuento_id"], item["nombre"], item["tipo_producto_id"])
    target = agregado["descuentos"].setdefault(key, {**item})
    if target is not item:
        target["monto"] += item["monto"]


def agrupar_por_dia_turno(registros):
    grupos = defaultdict(lambda: {
        "encontrados": {},
        "no_encontrados": {},
        "descuentos": {},
    })

    for item in registros:
        punto_venta_id, clasificado = clasificar_item(item)
        key = (punto_venta_id, item["fecha"], item["turno_id"])
        agregar_item(grupos[key], clasificado)

    return grupos


def serializar_items(items):
    return [
        {k: v for k, v in item.items() if k != "clase"}
        for item in items.values()
    ]


def calcular_totales(encontrados, no_encontrados, descuentos):
    subtotal = sum(item["total"] for item in encontrados)
    subtotal += sum(item["total"] for item in no_encontrados)
    descuento = sum(item["monto"] for item in descuentos)
    costo_total = sum(item["costo_total"] for item in encontrados)
    costo_total += sum(item["costo_total"] for item in no_encontrados)
    total = subtotal + descuento
    utilidad = total - costo_total
    margen = (utilidad / total * 100) if total else 0
    return {
        "subtotal": round(subtotal, 2),
        "descuento": round(descuento, 2),
        "total": round(total, 2),
        "costo_total": round(costo_total, 2),
        "utilidad": round(utilidad, 2),
        "margen": round(margen, 4),
    }


def construir_json_turno(turno_id, agregado):
    encontrados = serializar_items(agregado["encontrados"])
    no_encontrados = serializar_items(agregado["no_encontrados"])
    descuentos = serializar_items(agregado["descuentos"])
    totales = calcular_totales(encontrados, no_encontrados, descuentos)

    return {
        "turno_id": turno_id,
        "nombre": TURNOS[turno_id]["nombre"],
        **totales,
        "encontrados": encontrados,
        "no_encontrados": no_encontrados,
        "descuentos": descuentos,
    }


def turno_vacio(turno_id):
    return {
        "turno_id": turno_id,
        "nombre": TURNOS[turno_id]["nombre"],
        "subtotal": 0,
        "descuento": 0,
        "total": 0,
        "costo_total": 0,
        "utilidad": 0,
        "margen": 0,
        "encontrados": [],
        "no_encontrados": [],
        "descuentos": [],
    }


def sumar_turnos(turno_manana, turno_tarde):
    totales = {
        campo: float(turno_manana[campo] or 0) + float(turno_tarde[campo] or 0)
        for campo in ("subtotal", "descuento", "total", "costo_total")
    }
    totales["utilidad_bruta"] = totales["total"] - totales["costo_total"]
    totales["margen"] = (totales["utilidad_bruta"] / totales["total"] * 100) if totales["total"] else 0
    return {campo: round(valor, 2) for campo, valor in totales.items()}


def obtener_o_crear_venta_anual(cur, punto_venta_id, anio):
    cur.execute("""
        INSERT INTO ventas_anuales (punto_venta_id, anio)
        VALUES (%s, %s)
        ON CONFLICT (punto_venta_id, anio) DO UPDATE SET
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
    """, (punto_venta_id, anio))
    return cur.fetchone()["id"]


def obtener_o_crear_venta_mensual(cur, venta_anual_id, mes):
    cur.execute("""
        INSERT INTO ventas_mensuales (venta_anual_id, mes)
        VALUES (%s, %s)
        ON CONFLICT (venta_anual_id, mes) DO UPDATE SET
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
    """, (venta_anual_id, mes))
    return cur.fetchone()["id"]


def guardar_venta_diaria(cur, punto_venta_id, fecha, turno_manana, turno_tarde):
    venta_anual_id = obtener_o_crear_venta_anual(cur, punto_venta_id, fecha.year)
    venta_mensual_id = obtener_o_crear_venta_mensual(cur, venta_anual_id, fecha.month)
    totales = sumar_turnos(turno_manana, turno_tarde)

    cur.execute("""
        INSERT INTO ventas_diarias (
            venta_mensual_id, dia, fecha, turno_manana, turno_tarde,
            subtotal, descuento, total, costo_total, utilidad_bruta, margen
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (venta_mensual_id, dia) DO UPDATE SET
            fecha = EXCLUDED.fecha,
            turno_manana = EXCLUDED.turno_manana,
            turno_tarde = EXCLUDED.turno_tarde,
            subtotal = EXCLUDED.subtotal,
            descuento = EXCLUDED.descuento,
            total = EXCLUDED.total,
            costo_total = EXCLUDED.costo_total,
            utilidad_bruta = EXCLUDED.utilidad_bruta,
            margen = EXCLUDED.margen,
            updated_at = CURRENT_TIMESTAMP
    """, (
        venta_mensual_id,
        fecha.day,
        fecha,
        Json(turno_manana),
        Json(turno_tarde),
        totales["subtotal"],
        totales["descuento"],
        totales["total"],
        totales["costo_total"],
        totales["utilidad_bruta"],
        totales["margen"],
    ))


def actualizar_venta_mensual(cur, punto_venta_id, anio, mes):
    cur.execute("""
        WITH mensual AS (
            SELECT
                vm.id AS venta_mensual_id,
                COALESCE(SUM(vd.subtotal), 0) AS subtotal,
                COALESCE(SUM(vd.descuento), 0) AS descuento,
                COALESCE(SUM(vd.total), 0) AS total,
                COALESCE(SUM(vd.costo_total), 0) AS costo_total,
                COALESCE(SUM(vd.utilidad_bruta), 0) AS utilidad_bruta
            FROM ventas_mensuales vm
            JOIN ventas_anuales va ON va.id = vm.venta_anual_id
            LEFT JOIN ventas_diarias vd ON vd.venta_mensual_id = vm.id
            WHERE va.punto_venta_id = %s
              AND va.anio = %s
              AND vm.mes = %s
            GROUP BY vm.id
        )
        UPDATE ventas_mensuales AS vm
        SET
            subtotal = mensual.subtotal,
            descuento = mensual.descuento,
            total = mensual.total,
            costo_total = mensual.costo_total,
            utilidad_bruta = mensual.utilidad_bruta,
            margen = CASE
                WHEN mensual.total > 0
                THEN mensual.utilidad_bruta / mensual.total * 100
                ELSE 0
            END,
            updated_at = CURRENT_TIMESTAMP
        FROM mensual
        WHERE vm.id = mensual.venta_mensual_id
    """, (punto_venta_id, anio, mes))


def actualizar_venta_anual(cur, punto_venta_id, anio):
    cur.execute("""
        WITH anual AS (
            SELECT
                va.id AS venta_anual_id,
                COALESCE(SUM(vm.subtotal), 0) AS subtotal,
                COALESCE(SUM(vm.descuento), 0) AS descuento,
                COALESCE(SUM(vm.total), 0) AS total,
                COALESCE(SUM(vm.costo_total), 0) AS costo_total,
                COALESCE(SUM(vm.utilidad_bruta), 0) AS utilidad_bruta
            FROM ventas_anuales va
            LEFT JOIN ventas_mensuales vm ON vm.venta_anual_id = va.id
            WHERE va.punto_venta_id = %s
              AND va.anio = %s
            GROUP BY va.id
        )
        UPDATE ventas_anuales AS va
        SET
            subtotal = anual.subtotal,
            descuento = anual.descuento,
            total = anual.total,
            costo_total = anual.costo_total,
            utilidad_bruta = anual.utilidad_bruta,
            margen = CASE
                WHEN anual.total > 0
                THEN anual.utilidad_bruta / anual.total * 100
                ELSE 0
            END,
            updated_at = CURRENT_TIMESTAMP
        FROM anual
        WHERE va.id = anual.venta_anual_id
    """, (punto_venta_id, anio))


def guardar_ventas(cur, grupos):
    dias = defaultdict(dict)
    periodos = set()

    for (punto_venta_id, fecha, turno_id), agregado in grupos.items():
        dias[(punto_venta_id, fecha)][turno_id] = construir_json_turno(turno_id, agregado)

    for (punto_venta_id, fecha), turnos in sorted(dias.items(), key=lambda item: (item[0][0], item[0][1])):
        turno_manana = turnos.get(1, turno_vacio(1))
        turno_tarde = turnos.get(2, turno_vacio(2))
        guardar_venta_diaria(cur, punto_venta_id, fecha, turno_manana, turno_tarde)
        periodos.add((punto_venta_id, fecha.year, fecha.month))

    for punto_venta_id, anio, mes in sorted(periodos):
        actualizar_venta_mensual(cur, punto_venta_id, anio, mes)

    for punto_venta_id, anio in sorted({(pv, anio) for pv, anio, _ in periodos}):
        actualizar_venta_anual(cur, punto_venta_id, anio)

    return len(dias), len(periodos)


def main():
    reporte = encontrar_reporte_excel()
    log(f"Leyendo reporte Excel: {os.path.basename(reporte)}")

    conn = make_connection()
    try:
        with conn.cursor() as cur:
            cargar_catalogos(cur)
            registros = leer_reporte_excel(reporte)
            if not registros:
                raise ValueError(
                    "El reporte no generó registros válidos. Revisa FECHA_INICIO/FECHA_FIN, "
                    "nombres de hojas contra puntos_venta y columnas del Excel."
                )
            log(f"Registros válidos leídos: {len(registros)}")
            grupos = agrupar_por_dia_turno(registros)
            log(f"Grupos por punto de venta, día y turno: {len(grupos)}")
            dias, meses = guardar_ventas(cur, grupos)
            conn.commit()
            log(f"Ventas diarias actualizadas: {dias}")
            log(f"Ventas mensuales recalculadas: {meses}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    log("Carga de ventas desde Excel completada")


if __name__ == "__main__":
    main()
