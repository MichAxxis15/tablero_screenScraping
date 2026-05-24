import os
import re
import json
import unicodedata
from collections import defaultdict

import pandas as pd
import psycopg2

from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv("config.env")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EXCEL_PATH = os.getenv("EXCEL_PATH")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     os.getenv("DB_PORT"),
    "dbname":   os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

PLATILLOS = {}
TIPOS = {}
PUNTOS_VENTA = {}
DESCUENTOS = {}


def conectar():
    conn = psycopg2.connect(
        **DB_CONFIG,
        options="-c search_path=datum_inter",
        cursor_factory=RealDictCursor,
    )
    return conn

def normalizar(valor):
    if valor is None:
        return ""
    valor = str(valor).lower().strip()
    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(c for c in valor if not unicodedata.combining(c))
    valor = re.sub(r"[^a-z0-9\s]", " ", valor)
    valor = re.sub(r"\s+", " ", valor)
    return valor.strip()

def cargar_catalogos(cur):
    global PLATILLOS, TIPOS, PUNTOS_VENTA, DESCUENTOS

    cur.execute("SELECT id, nombre, costo_manual FROM platillos WHERE status=1")
    PLATILLOS = {normalizar(x["nombre"]): x for x in cur.fetchall()}

    cur.execute(
        "SELECT id, nombre, punto_venta_id FROM tipos_producto WHERE status=1")
    TIPOS = {normalizar(x["nombre"]): x for x in cur.fetchall()}

    cur.execute("SELECT id, nombre FROM puntos_venta WHERE status=1")
    PUNTOS_VENTA = {normalizar(x["nombre"]): x for x in cur.fetchall()}

    cur.execute("""
        SELECT id, nombre, punto_venta_id
        FROM descuentos
        WHERE status=1
    """)
    DESCUENTOS = {
        (normalizar(x["nombre"]), x["punto_venta_id"]): x
        for x in cur.fetchall()
    }

    print(f"Catálogos cargados → platillos: {len(PLATILLOS)}, "
          f"tipos: {len(TIPOS)}, puntos_venta: {len(PUNTOS_VENTA)}, "
          f"descuentos: {len(DESCUENTOS)}")


def detectar_turno(fecha):
    hora = fecha.hour
    if 7 <= hora <= 13:
        return 1
    if hora >= 14 or hora <= 3:
        return 2
    return None


def resolver_punto_real(punto_origen, tipo):
    if tipo and tipo["punto_venta_id"]:
        return tipo["punto_venta_id"]
    return punto_origen


def es_descuento(producto, tipo):
    if producto.startswith("descuento"):
        return True
    if tipo and normalizar(tipo["nombre"]) == "descuentos":
        return True
    return False


def obtener_excel():
    if EXCEL_PATH:
        ruta = EXCEL_PATH if os.path.isabs(
            EXCEL_PATH) else os.path.join(BASE_DIR, EXCEL_PATH)
        if os.path.exists(ruta):
            return ruta
    raise FileNotFoundError(f"EXCEL_PATH no encontrado: {EXCEL_PATH!r}")


def buscar_punto_venta(hoja):
    hoja = normalizar(hoja)
    if hoja in PUNTOS_VENTA:
        return PUNTOS_VENTA[hoja]
    for nombre, pv in PUNTOS_VENTA.items():
        if nombre in hoja or hoja in nombre:
            return pv
    return None


def leer_excel():
    archivo = obtener_excel()
    hojas = pd.read_excel(archivo, sheet_name=None)
    registros = []
    filas_fallidas = []

    for nombre_hoja, df in hojas.items():
        print(f"\nHoja: {nombre_hoja!r}")
        punto = buscar_punto_venta(nombre_hoja)

        if punto is None:
            print("  → sin punto de venta, se omite")
            continue

        if df.empty:
            print("  → hoja vacía, se omite")
            continue

        df.columns = [normalizar(x) for x in df.columns]

        requeridas = {"producto", "tipo", "cantidad", "total ventas", "fecha"}
        faltan = requeridas - set(df.columns)
        if faltan:
            print(f"  → faltan columnas: {faltan}, se omite")
            continue

        for idx, row in df.iterrows():
            try:
                fecha = pd.to_datetime(row["fecha"])
            except Exception as e:
                filas_fallidas.append(
                    {"hoja": nombre_hoja, "fila": idx, "error": str(e)})
                continue

            turno = detectar_turno(fecha)
            if turno is None:
                continue

            producto = normalizar(row["producto"])
            tipo_txt = normalizar(row["tipo"])
            tipo = TIPOS.get(tipo_txt)

            try:
                cantidad = float(row["cantidad"] or 0)
                total = float(row["total ventas"] or 0)
            except (ValueError, TypeError):
                filas_fallidas.append(
                    {"hoja": nombre_hoja, "fila": idx, "error": "cantidad/total inválido"})
                continue

            pv_real = resolver_punto_real(punto["id"], tipo)

            registros.append({
                "fecha":            fecha.date(),
                "hora":             fecha.time(),
                "turno":            turno,
                "producto":         producto,
                "tipo":             tipo,
                "cantidad":         cantidad,
                "total":            total,
                "punto_venta_real": pv_real,
            })

    print(f"\nRegistros leídos: {len(registros)}")
    if filas_fallidas:
        print(f"Filas con error: {len(filas_fallidas)}")
        for f in filas_fallidas[:10]:
            print(f"  {f}")

    return registros


def agrupar_registros(registros):
    grupos = defaultdict(lambda: {
        "turno_manana":   [],
        "turno_tarde":    [],
        "encontrados":    [],
        "no_encontrados": [],
        "descuentos":     [],
        "subtotal":       0.0,
        "descuento":      0.0,
        "total":          0.0,
    })

    for item in registros:
        key = (item["punto_venta_real"], item["fecha"])
        grupo = grupos[key]

        registro = {
            "producto": item["producto"],
            "cantidad": item["cantidad"],
            "venta":    item["total"],
        }

        # Turno
        if item["turno"] == 1:
            grupo["turno_manana"].append(registro)
        else:
            grupo["turno_tarde"].append(registro)

        # Descuentos
        if es_descuento(item["producto"], item["tipo"]):
            grupo["descuentos"].append(registro)
            monto_desc = abs(item["total"])
            grupo["descuento"] += monto_desc
            # suma (valor negativo en el POS)
            grupo["subtotal"] += item["total"]
            grupo["total"] = grupo["subtotal"] - grupo["descuento"]
            continue

        # Platillos
        platillo = PLATILLOS.get(item["producto"])
        if platillo:
            costo_unit = float(platillo.get("costo_manual") or 0)
            grupo["encontrados"].append({
                **registro,
                "platillo_id": platillo["id"],
                "costo":       round(costo_unit * item["cantidad"], 2),
            })
        else:
            grupo["no_encontrados"].append({
                **registro,
                "costo": 0,
            })

        grupo["subtotal"] += item["total"]
        grupo["total"] = grupo["subtotal"] - grupo["descuento"]

    return grupos


def upsert_venta_anual(cur, punto_venta_id, anio):
    """Obtiene o crea el registro ventas_anuales. Devuelve su id."""
    cur.execute("""
        INSERT INTO ventas_anuales (punto_venta_id, anio)
        VALUES (%s, %s)
        ON CONFLICT (punto_venta_id, anio) DO NOTHING
    """, (punto_venta_id, anio))

    cur.execute("""
        SELECT id FROM ventas_anuales
        WHERE punto_venta_id = %s AND anio = %s
    """, (punto_venta_id, anio))
    return cur.fetchone()["id"]


def upsert_venta_mensual(cur, venta_anual_id, mes):
    """Obtiene o crea el registro ventas_mensuales. Devuelve su id."""
    cur.execute("""
        INSERT INTO ventas_mensuales (venta_anual_id, mes)
        VALUES (%s, %s)
        ON CONFLICT (venta_anual_id, mes) DO NOTHING
    """, (venta_anual_id, mes))

    cur.execute("""
        SELECT id FROM ventas_mensuales
        WHERE venta_anual_id = %s AND mes = %s
    """, (venta_anual_id, mes))
    return cur.fetchone()["id"]


def calcular_metricas_dia(grupo):
    """Calcula costo_total, utilidad_bruta y margen a partir de encontrados."""
    costo_total = sum(e.get("costo", 0) for e in grupo["encontrados"])
    total = grupo["total"]
    utilidad = round(total - costo_total, 2)
    margen = round((utilidad / total * 100), 4) if total else 0.0
    return costo_total, utilidad, margen


def upsert_venta_diaria(cur, venta_mensual_id, fecha, grupo):
    """
    Inserta o actualiza ventas_diarias.
    Si ya existe el registro del día, suma los valores nuevos al existente
    (comportamiento útil cuando se reimporta el mismo Excel).
    """
    dia = fecha.day

    costo_total, utilidad, margen = calcular_metricas_dia(grupo)

    cur.execute("""
        INSERT INTO ventas_diarias (
            venta_mensual_id,
            dia,
            fecha,
            turno_manana,
            turno_tarde,
            encontrados,
            no_encontrados,
            descuentos,
            subtotal,
            descuento,
            total,
            costo_total,
            utilidad_bruta,
            margen
        )
        VALUES (
            %s, %s, %s,
            %s::jsonb, %s::jsonb,
            %s::jsonb, %s::jsonb, %s::jsonb,
            %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (venta_mensual_id, dia) DO UPDATE SET
            turno_manana   = ventas_diarias.turno_manana   || EXCLUDED.turno_manana,
            turno_tarde    = ventas_diarias.turno_tarde    || EXCLUDED.turno_tarde,
            encontrados    = ventas_diarias.encontrados    || EXCLUDED.encontrados,
            no_encontrados = ventas_diarias.no_encontrados || EXCLUDED.no_encontrados,
            descuentos     = ventas_diarias.descuentos     || EXCLUDED.descuentos,
            subtotal       = ventas_diarias.subtotal       + EXCLUDED.subtotal,
            descuento      = ventas_diarias.descuento      + EXCLUDED.descuento,
            total          = ventas_diarias.total          + EXCLUDED.total,
            costo_total    = ventas_diarias.costo_total    + EXCLUDED.costo_total,
            utilidad_bruta = ventas_diarias.utilidad_bruta + EXCLUDED.utilidad_bruta,
            margen         = EXCLUDED.margen,
            updated_at     = CURRENT_TIMESTAMP
    """, (
        venta_mensual_id,
        dia,
        fecha,
        json.dumps(grupo["turno_manana"]),
        json.dumps(grupo["turno_tarde"]),
        json.dumps(grupo["encontrados"]),
        json.dumps(grupo["no_encontrados"]),
        json.dumps(grupo["descuentos"]),
        round(grupo["subtotal"], 2),
        round(grupo["descuento"], 2),
        round(grupo["total"],    2),
        round(costo_total,       2),
        utilidad,
        margen,
    ))


def actualizar_venta_mensual(cur, venta_mensual_id):
    """Recalcula totales del mes sumando todos sus días."""
    cur.execute("""
        UPDATE ventas_mensuales vm
        SET
            subtotal       = sub.subtotal,
            descuento      = sub.descuento,
            total          = sub.total,
            costo_total    = sub.costo_total,
            utilidad_bruta = sub.utilidad_bruta,
            margen         = CASE WHEN sub.total > 0
                                  THEN ROUND((sub.utilidad_bruta / sub.total) * 100, 4)
                                  ELSE 0 END,
            updated_at     = CURRENT_TIMESTAMP
        FROM (
            SELECT
                SUM(subtotal)       AS subtotal,
                SUM(descuento)      AS descuento,
                SUM(total)          AS total,
                SUM(costo_total)    AS costo_total,
                SUM(utilidad_bruta) AS utilidad_bruta
            FROM ventas_diarias
            WHERE venta_mensual_id = %s
        ) sub
        WHERE vm.id = %s
    """, (venta_mensual_id, venta_mensual_id))


def actualizar_venta_anual(cur, venta_anual_id):
    """Recalcula totales del año sumando todos sus meses."""
    cur.execute("""
        UPDATE ventas_anuales va
        SET
            subtotal       = sub.subtotal,
            descuento      = sub.descuento,
            total          = sub.total,
            costo_total    = sub.costo_total,
            utilidad_bruta = sub.utilidad_bruta,
            margen         = CASE WHEN sub.total > 0
                                  THEN ROUND((sub.utilidad_bruta / sub.total) * 100, 4)
                                  ELSE 0 END,
            updated_at     = CURRENT_TIMESTAMP
        FROM (
            SELECT
                SUM(subtotal)       AS subtotal,
                SUM(descuento)      AS descuento,
                SUM(total)          AS total,
                SUM(costo_total)    AS costo_total,
                SUM(utilidad_bruta) AS utilidad_bruta
            FROM ventas_mensuales
            WHERE venta_anual_id = %s
        ) sub
        WHERE va.id = %s
    """, (venta_anual_id, venta_anual_id))


def persistir_grupos(cur, grupos):
    """
    Recorre todos los grupos (punto_venta_real, fecha) e inserta / actualiza
    la jerarquía ventas_anuales → ventas_mensuales → ventas_diarias.
    """
    # Conjuntos para saber qué mensuales y anuales actualizar al final
    mensuales_tocados = set()
    anuales_tocados = {}   # venta_anual_id → (punto_venta_id, anio)

    total_grupos = len(grupos)
    print(f"\nInsertando {total_grupos} grupos en la BD...")

    for i, ((punto_venta_id, fecha), grupo) in enumerate(grupos.items(), 1):
        anio = fecha.year
        mes = fecha.month

        va_id = upsert_venta_anual(cur, punto_venta_id, anio)
        vm_id = upsert_venta_mensual(cur, va_id, mes)

        upsert_venta_diaria(cur, vm_id, fecha, grupo)

        mensuales_tocados.add(vm_id)
        anuales_tocados[va_id] = (punto_venta_id, anio)

        if i % 50 == 0 or i == total_grupos:
            print(f"  {i}/{total_grupos} grupos procesados")

    # Recalcular jerárquicamente
    print("Recalculando totales mensuales...")
    for vm_id in mensuales_tocados:
        actualizar_venta_mensual(cur, vm_id)

    print("Recalculando totales anuales...")
    for va_id in anuales_tocados:
        actualizar_venta_anual(cur, va_id)

    print("Persistencia completada.")

def imprimir_resumen(grupos):
    print("\n" + "=" * 60)
    print("RESUMEN DE IMPORTACIÓN")
    print("=" * 60)

    total_ventas = 0.0
    total_descuentos = 0.0
    total_encontrados = 0
    total_no_encontrados = 0

    for (pv_id, fecha), grupo in grupos.items():
        total_ventas += grupo["total"]
        total_descuentos += grupo["descuento"]
        total_encontrados += len(grupo["encontrados"])
        total_no_encontrados += len(grupo["no_encontrados"])

    print(f"Grupos (punto_venta × día): {len(grupos)}")
    print(f"Venta total neta:           ${total_ventas:,.2f}")
    print(f"Descuentos totales:         ${total_descuentos:,.2f}")
    print(f"Platillos encontrados:      {total_encontrados}")
    print(f"Productos no encontrados:   {total_no_encontrados}")
    print("=" * 60)

    if total_no_encontrados:
        print("\nProductos sin coincidencia en catálogo (primeros 20):")
        vistos = set()
        for grupo in grupos.values():
            for p in grupo["no_encontrados"]:
                if p["producto"] not in vistos:
                    print(f"  • {p['producto']}")
                    vistos.add(p["producto"])
                if len(vistos) >= 20:
                    break
            if len(vistos) >= 20:
                break

def main():
    conn = conectar()

    try:
        with conn.cursor() as cur:
            # Etapas 1–4: catálogos y lectura
            cargar_catalogos(cur)
            registros = leer_excel()

            if not registros:
                print(
                    "Sin registros para importar. Revisa el Excel y las columnas requeridas.")
                return

            # Etapas 5–8: agrupación
            grupos = agrupar_registros(registros)
            imprimir_resumen(grupos)

            # Etapas 9–10: persistencia
            persistir_grupos(cur, grupos)

        conn.commit()
        print("\n✓ Importación completada y confirmada en la base de datos.")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error durante la importación: {e}")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
