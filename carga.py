import pandas as pd
import pymysql
import os
import math
import logging
from dotenv import load_dotenv
from contextlib import contextmanager
from collections import defaultdict

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

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

@contextmanager
def get_db_connection():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logging.error(f"Rollback por error: {e}")
        raise e
    finally:
        conn.close()

# Limpieza
def limpiar_nan(valor):
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return None
    return valor

def limpiar_texto(texto):
    texto = limpiar_nan(texto)
    return str(texto).strip().lower() if texto else None

def limpiar_numero(valor, default=0):
    valor = limpiar_nan(valor)
    try:
        return float(valor) if valor is not None else default
    except (ValueError, TypeError):
        return default

def obtener_entero(valor):
    valor = limpiar_nan(valor)
    try:
        return int(float(valor)) if valor is not None else None
    except (ValueError, TypeError):
        return None

def aplicar_merma(cantidad, merma):
    """Aplica merma SOLO si existe"""
    if merma is None:
        return cantidad
    merma_val = limpiar_numero(merma, 0)
    if merma_val > 0:
        return cantidad * (1 + merma_val / 100)
    return cantidad

# Unidades
def normalizar_unidad(u):
    u = limpiar_texto(u)
    mapa = {
        "ml": "ml", "mililitro": "ml", "mililitros": "ml",
        "lt": "lt", "l": "lt", "litro": "lt", "litros": "lt",
        "gr": "gr", "g": "gr", "gramo": "gr", "gramos": "gr",
        "kg": "kg", "kilogramo": "kg",
        "pz": "pz", "pieza": "pz", "pza": "pz", "und": "pz", "unidad": "pz"
    }
    return mapa.get(u, u)

def convertir_a_base(cantidad, unidad):
    """Convierte a unidad base (lt, kg, pz)"""
    unidad = normalizar_unidad(unidad)
    
    if unidad == "ml":
        return cantidad / 1000, "lt"
    elif unidad == "gr":
        return cantidad / 1000, "kg"
    return cantidad, unidad

# Cache 
class CacheManager:    
    def __init__(self, cursor):
        self.cursor = cursor
        self.categorias = {}
        self.articulos = {}
        self.subrecetas = {}
        self.unidades = {}
        self._load_all()
    
    def _load_all(self):
        """Carga todos los datos necesarios de una vez - SIN columna status"""
        logging.info("Cargando cachés...")
        
        self.cursor.execute("SELECT id, nombre FROM categorias_producto")
        for row in self.cursor.fetchall():
            self.categorias[limpiar_texto(row["nombre"])] = row["id"]
        
        self.cursor.execute("""
            SELECT 
                id, 
                numero_articulo, 
                costo_unitario,
                contenido,
                unidad_medida_id
            FROM articulos
        """)
        for row in self.cursor.fetchall():
            self.articulos[row["numero_articulo"]] = {
                "id": row["id"],
                "costo_unitario": float(row["costo_unitario"] or 0),
                "contenido": float(row["contenido"] or 1),
                "unidad_id": row["unidad_medida_id"]
            }
        
        # Subrecetas - SIN WHERE status
        self.cursor.execute("SELECT id, nombre FROM subrecetas")
        for row in self.cursor.fetchall():
            self.subrecetas[limpiar_texto(row["nombre"])] = row["id"]
        
        # Unidades de medida
        self.cursor.execute("SELECT id, clave FROM unidades_medida")
        for row in self.cursor.fetchall():
            self.unidades[limpiar_texto(row["clave"])] = row["id"]
        
        logging.info(f"Cachés cargados: {len(self.categorias)} cats, {len(self.articulos)} arts, "
                    f"{len(self.subrecetas)} subs, {len(self.unidades)} units")
    
    def get_categoria_id(self, nombre):
        return self.categorias.get(limpiar_texto(nombre))
    
    def get_articulo(self, numero):
        return self.articulos.get(numero)
    
    def get_subreceta_id(self, nombre):
        if not nombre:
            return None
        return self.subrecetas.get(limpiar_texto(nombre))
    
    def get_unidad_id(self, clave):
        return self.unidades.get(normalizar_unidad(clave))
    
    def add_subreceta(self, nombre, sub_id):
        self.subrecetas[limpiar_texto(nombre)] = sub_id

# Calculo costos
def calcular_costo_componente(cantidad, articulo_info):
    """
    Calcula el costo real de un componente
    cantidad: cantidad en la receta (ya convertida a unidad base de la receta)
    articulo_info: dict con costo_unitario y contenido
    
    Fórmula: Costo = cantidad * (costo_unitario / contenido)
    """
    if not articulo_info:
        return 0
    
    costo_unitario = articulo_info["costo_unitario"]
    contenido = articulo_info["contenido"]
    
    if contenido <= 0:
        contenido = 1
    
    # Costo por unidad base
    costo_por_unidad_base = costo_unitario / contenido
    
    # Costo total
    return cantidad * costo_por_unidad_base

def actualizar_costo_parcial_componentes(cursor, tabla, receta_id):
    """
    Actualiza los costos_parciales de todos los componentes de una receta
    """
    if tabla == 'subreceta_componentes':
        campo_id = 'subreceta_padre_id'
        tabla_principal = 'subrecetas'
    else:
        campo_id = 'platillo_id'
        tabla_principal = 'platillos'
    
    cursor.execute(f"""
        UPDATE {tabla} pc
        JOIN articulos a ON pc.articulo_id = a.id
        SET pc.costo_parcial = ROUND(pc.cantidad * (a.costo_unitario / NULLIF(a.contenido, 0)), 2)
        WHERE pc.{campo_id} = %s AND pc.articulo_id IS NOT NULL
    """, (receta_id,))
    
    # Para componentes que son subrecetas (costo_manual)
    cursor.execute(f"""
        UPDATE {tabla} pc
        SET pc.costo_parcial = 0
        WHERE pc.{campo_id} = %s AND pc.subreceta_id IS NOT NULL
    """, (receta_id,))

def actualizar_costo_platillo(cursor, platillo_id):
    """Actualiza el costo_manual del platillo sumando sus componentes"""
    cursor.execute("""
        UPDATE platillos p
        SET p.costo_manual = (
            SELECT COALESCE(SUM(pc.costo_parcial), 0)
            FROM platillo_componentes pc
            WHERE pc.platillo_id = p.id
        )
        WHERE p.id = %s
    """, (platillo_id,))

def procesar_subrecetas(cursor, cache, df):
    """Procesa subrecetas en batch"""
    logging.info("Procesando subrecetas...")
    
    # Crear subrecetas nuevas
    subrecetas_a_crear = []
    for _, row in df.iterrows():
        nombre = limpiar_texto(row.get("producto"))
        unidad = row.get("u.medida")
        
        if not nombre or nombre in cache.subrecetas:
            continue
        
        unidad_id = cache.get_unidad_id(unidad)
        if unidad_id:
            subrecetas_a_crear.append((nombre, 1, unidad_id))
    
    if subrecetas_a_crear:
        cursor.executemany("""
            INSERT INTO subrecetas(nombre, rendimiento, unidad_medida_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                rendimiento = VALUES(rendimiento),
                unidad_medida_id = VALUES(unidad_medida_id),
                updated_at = NOW()
        """, subrecetas_a_crear)
        
        # Actualizar caché con nuevas subrecetas
        for nombre, _, _ in subrecetas_a_crear:
            cursor.execute("SELECT id FROM subrecetas WHERE nombre = %s", (nombre,))
            result = cursor.fetchone()
            if result:
                cache.add_subreceta(nombre, result["id"])
    
    # Preparar componentes en batch
    componentes = []
    actual_nombre = None
    actual_id = None
    stats = {"totales": 0, "con_articulo": 0, "con_subreceta": 0, "errores": 0}
    
    for idx, row in df.iterrows():
        nombre = limpiar_texto(row.get("producto"))
        if not nombre:
            continue
        
        # Cambió de subreceta
        if nombre != actual_nombre:
            actual_nombre = nombre
            actual_id = cache.get_subreceta_id(nombre)
            if not actual_id:
                logging.warning(f"No se encontró ID para subreceta: {nombre}")
                continue
            
            # Limpiar componentes existentes
            cursor.execute("DELETE FROM subreceta_componentes WHERE subreceta_padre_id = %s", (actual_id,))
        
        cantidad = limpiar_numero(row.get("cantidad"))
        merma = row.get("merma")
        cantidad_con_merma = aplicar_merma(cantidad, merma)
        cantidad_base, _ = convertir_a_base(cantidad_con_merma, row.get("u.medida"))
        
        # Determinar si es artículo o subreceta
        numero_articulo = obtener_entero(row.get("artículo"))
        nombre_ingrediente = limpiar_texto(row.get("ingrediente"))
        
        articulo_id = None
        subreceta_id = None
        costo_parcial = 0
        
        if numero_articulo:
            articulo = cache.get_articulo(numero_articulo)
            if articulo:
                articulo_id = articulo["id"]
                costo_parcial = calcular_costo_componente(cantidad_base, articulo)
                stats["con_articulo"] += 1
            else:
                logging.warning(f"Artículo no encontrado: {numero_articulo} para receta {nombre}")
                stats["errores"] += 1
                
        elif nombre_ingrediente:
            subreceta_id = cache.get_subreceta_id(nombre_ingrediente)
            if subreceta_id:
                stats["con_subreceta"] += 1
            else:
                logging.warning(f"Subreceta no encontrada: {nombre_ingrediente} para receta {nombre}")
                stats["errores"] += 1
        
        if articulo_id or subreceta_id:
            componentes.append((actual_id, articulo_id, subreceta_id, cantidad_base, costo_parcial))
            stats["totales"] += 1
    
    if componentes:
        cursor.executemany("""
            INSERT INTO subreceta_componentes
            (subreceta_padre_id, articulo_id, subreceta_id, cantidad, costo_parcial, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """, componentes)
        
        logging.info(f"✅ Subrecetas: {stats['totales']} componentes procesados "
                    f"({stats['con_articulo']} artículos, {stats['con_subreceta']} subrecetas, {stats['errores']} errores)")

def procesar_productos(cursor, cache, df, tipo):
    """Procesa platillos o bebidas en batch"""
    logging.info(f"Procesando {tipo}...")
    
    # Forward fill de productos
    if df["producto"].isnull().any():
        df["producto"] = df["producto"].ffill()
    
    productos_procesados = {}
    componentes = []
    stats = {"totales": 0, "con_articulo": 0, "con_subreceta": 0, "errores": 0, "productos": 0}
    
    for idx, row in df.iterrows():
        nombre = limpiar_texto(row.get("producto"))
        if not nombre:
            continue
        
        # Crear producto si no existe
        if nombre not in productos_procesados:
            categoria_id = cache.get_categoria_id(row.get("grupo"))
            if not categoria_id:
                logging.warning(f"Categoría no encontrada para {nombre}")
                continue
            
            # Verificar si ya existe
            cursor.execute("SELECT id FROM platillos WHERE nombre = %s", (nombre,))
            existente = cursor.fetchone()
            
            if existente:
                producto_id = existente["id"]
            else:
                cursor.execute("""
                    INSERT INTO platillos(nombre, categoria_id, created_at, updated_at)
                    VALUES (%s, %s, NOW(), NOW())
                """, (nombre, categoria_id))
                producto_id = cursor.lastrowid
            
            productos_procesados[nombre] = producto_id
            stats["productos"] += 1
            
            # Limpiar componentes existentes
            cursor.execute("DELETE FROM platillo_componentes WHERE platillo_id = %s", (producto_id,))
        
        producto_id = productos_procesados[nombre]
        
        # Procesar componente
        cantidad = limpiar_numero(row.get("cantidad"))
        merma = row.get("merma")
        cantidad_con_merma = aplicar_merma(cantidad, merma)
        cantidad_base, _ = convertir_a_base(cantidad_con_merma, row.get("u.medida"))
        
        numero_articulo = obtener_entero(row.get("artículo"))
        nombre_ingrediente = limpiar_texto(row.get("ingrediente"))
        
        articulo_id = None
        subreceta_id = None
        costo_parcial = 0
        
        if numero_articulo:
            articulo = cache.get_articulo(numero_articulo)
            if articulo:
                articulo_id = articulo["id"]
                costo_parcial = calcular_costo_componente(cantidad_base, articulo)
                stats["con_articulo"] += 1
            else:
                logging.warning(f"Artículo no encontrado: {numero_articulo} para {nombre}")
                stats["errores"] += 1
                
        elif nombre_ingrediente:
            subreceta_id = cache.get_subreceta_id(nombre_ingrediente)
            if subreceta_id:
                stats["con_subreceta"] += 1
            else:
                logging.warning(f"Subreceta no encontrada: {nombre_ingrediente} para {nombre}")
                stats["errores"] += 1
        
        if articulo_id or subreceta_id:
            componentes.append((producto_id, articulo_id, subreceta_id, cantidad_base, costo_parcial))
            stats["totales"] += 1
    
    if componentes:
        cursor.executemany("""
            INSERT INTO platillo_componentes
            (platillo_id, articulo_id, subreceta_id, cantidad, costo_parcial, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """, componentes)
        
        # Actualizar costos de productos
        for prod_id in set([c[0] for c in componentes]):
            actualizar_costo_parcial_componentes(cursor, "platillo_componentes", prod_id)
            actualizar_costo_platillo(cursor, prod_id)
        
        logging.info(f"✅ {tipo}: {stats['productos']} productos, {stats['totales']} componentes "
                    f"({stats['con_articulo']} artículos, {stats['con_subreceta']} subrecetas, {stats['errores']} errores)")

# Generar reporte de costso
def generar_reporte_costos(cursor):
    logging.info("\n" + "="*50)
    logging.info("REPORTE DE COSTOS")
    logging.info("="*50)
    
    # Platillos costo_manual calculado
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(costo_manual) as suma_costos,
            AVG(costo_manual) as promedio,
            COUNT(CASE WHEN costo_manual IS NULL OR costo_manual = 0 THEN 1 END) as sin_costo
        FROM platillos
    """)
    result = cursor.fetchone()
    logging.info(f"Platillos: {result['total']} totales")
    logging.info(f"   - Con costo: {result['total'] - result['sin_costo']}")
    logging.info(f"   - Sin costo: {result['sin_costo']}")
    if result['suma_costos']:
        logging.info(f"   - Suma total: ${result['suma_costos']:.2f}")
        logging.info(f"   - Promedio: ${result['promedio']:.2f}")
    
    # Subrecetas
    cursor.execute("SELECT COUNT(*) as total FROM subrecetas")
    total_sub = cursor.fetchone()["total"]
    logging.info(f"Subrecetas: {total_sub} totales")
    
    # Componentes
    cursor.execute("SELECT COUNT(*) as total FROM platillo_componentes")
    total_comp = cursor.fetchone()["total"]
    logging.info(f"Componentes de platillos: {total_comp}")
    
    cursor.execute("SELECT COUNT(*) as total FROM subreceta_componentes")
    total_comp_sub = cursor.fetchone()["total"]
    logging.info(f"Componentes de subrecetas: {total_comp_sub}")

def main():
    if not os.path.exists(EXCEL_PATH):
        raise FileNotFoundError(f"No se encuentra el archivo: {EXCEL_PATH}")
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                logging.info("++++ Leyendo archivo Excel...")
                df_sub = pd.read_excel(EXCEL_PATH, sheet_name="Sub")
                df_plat = pd.read_excel(EXCEL_PATH, sheet_name="Platillos")
                df_beb = pd.read_excel(EXCEL_PATH, sheet_name="Bebidas")
                
                # Limpiar dataframes
                for df in [df_sub, df_plat, df_beb]:
                    df.columns = [c.strip().lower() for c in df.columns]
                    df = df.where(pd.notnull(df), None)
                
                # Cargar caché
                cache = CacheManager(cursor)
                
                logging.info("\nProcesando subrecetas...")
                procesar_subrecetas(cursor, cache, df_sub)
                
                # Recargar caché de subrecetas (para incluir las nuevas)
                logging.info("Actualizando caché de subrecetas...")
                cache.subrecetas = {}
                cursor.execute("SELECT id, nombre FROM subrecetas")
                for row in cursor.fetchall():
                    cache.subrecetas[limpiar_texto(row["nombre"])] = row["id"]
                
                logging.info("\n1.- Procesando platillos...")
                procesar_productos(cursor, cache, df_plat, "PLATILLOS")
                
                logging.info("\n2.- Procesando bebidas...")
                procesar_productos(cursor, cache, df_beb, "BEBIDAS")
                
                # Reporte final
                generar_reporte_costos(cursor)
                
                logging.info("\nPROCESO COMPLETADO ")
                
            except Exception as e:
                logging.error(f"❌ Error: {str(e)}")
                import traceback
                traceback.print_exc()
                raise

if __name__ == "__main__":
    main()