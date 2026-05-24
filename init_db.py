import psycopg2
from dotenv import load_dotenv
import os

load_dotenv("config.env")
load_dotenv()


def get_db_connection():
    """Obtiene conexión a la base de datos PostgreSQL."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


def schema_exists(cursor, schema_name):
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 
            FROM information_schema.schemata 
            WHERE schema_name = %s
        )
    """, (schema_name,))
    return cursor.fetchone()[0]


def table_exists(cursor, schema_name, table_name):
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 
            FROM information_schema.tables 
            WHERE table_schema = %s 
            AND table_name = %s
        )
    """, (schema_name, table_name))
    return cursor.fetchone()[0]


def crear_vista_resumen(cursor=None):
    """Crea o actualiza la vista de resumen por punto de venta."""
    owns_connection = cursor is None
    connexion = None

    try:
        if owns_connection:
            connexion = get_db_connection()
            cursor = connexion.cursor()
            cursor.execute("SET search_path TO datum_inter")

        cursor.execute("""
            CREATE OR REPLACE VIEW datum_inter.v_resumen_punto_venta AS
            WITH totales_globales AS (
                SELECT
                    COALESCE(SUM(va.total), 0)          AS gran_total_ventas,
                    COALESCE(SUM(va.costo_total), 0)    AS gran_total_costos,
                    COALESCE(SUM(va.utilidad_bruta), 0) AS gran_total_utilidad
                FROM datum_inter.ventas_anuales va
            ),
            detalle AS (
                SELECT
                    pv.nombre              AS punto_venta,
                    COALESCE(SUM(va.total), 0)          AS ventas,
                    COALESCE(SUM(va.costo_total), 0)    AS costos,
                    COALESCE(SUM(va.utilidad_bruta), 0) AS utilidad_bruta
                FROM datum_inter.ventas_anuales va
                JOIN datum_inter.puntos_venta pv ON pv.id = va.punto_venta_id
                GROUP BY pv.nombre
            )
            SELECT
                d.punto_venta AS punto_de_venta,
                d.ventas,
                ROUND((d.ventas / NULLIF(t.gran_total_ventas, 0)) * 100, 2) AS pct_ventas,
                d.costos,
                ROUND((d.costos / NULLIF(t.gran_total_costos, 0)) * 100, 2) AS pct_costos,
                d.utilidad_bruta AS ut_bruta,
                ROUND((d.utilidad_bruta / NULLIF(t.gran_total_utilidad, 0)) * 100, 2) AS pct_ut_bruta,
                ROUND((d.utilidad_bruta / NULLIF(d.ventas, 0)) * 100, 2) AS margen_pct
            FROM detalle d
            CROSS JOIN totales_globales t
            
            UNION ALL
            
            SELECT
                'Total',
                t.gran_total_ventas,
                100.00,
                t.gran_total_costos,
                100.00,
                t.gran_total_utilidad,
                100.00,
                ROUND((t.gran_total_utilidad / NULLIF(t.gran_total_ventas, 0)) * 100, 2)
            FROM totales_globales t
            WHERE t.gran_total_ventas > 0
        """)

        if owns_connection:
            connexion.commit()
    except Exception:
        if owns_connection and connexion:
            connexion.rollback()
        raise
    finally:
        if owns_connection and cursor:
            cursor.close()
        if owns_connection and connexion and not connexion.closed:
            connexion.close()


def initialize_database():
    connexion = None
    cursor = None

    try:
        connexion = get_db_connection()
        cursor = connexion.cursor()

        cursor.execute("CREATE SCHEMA IF NOT EXISTS datum_inter")
        cursor.execute("SET search_path TO datum_inter")

        if table_exists(cursor, 'datum_inter', 'puntos_venta'):
            cursor.execute("SELECT COUNT(*) FROM datum_inter.puntos_venta")
            count = cursor.fetchone()[0]
            if count > 0:
                print(
                    f"La base de datos ya contiene {count} registros en puntos_venta. Actualizando estructura...")
        else:
            print("Base de datos vacía. Inicializando estructura y datos...")

        cursor.execute("""
            CREATE OR REPLACE FUNCTION datum_inter.fn_set_updated_at()
            RETURNS TRIGGER LANGUAGE plpgsql AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$;
        """)

        print("Creando tabla: lineas")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.lineas (
                id      SERIAL PRIMARY KEY,
                nombre  VARCHAR(100) NOT NULL,
                status  SMALLINT     DEFAULT 1
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_lineas_nombre ON datum_inter.lineas (nombre)")

        print("Creando tabla: familias")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.familias (
                id        SERIAL PRIMARY KEY,
                nombre    VARCHAR(100) NOT NULL,
                linea_id  INT          NOT NULL REFERENCES datum_inter.lineas(id),
                status    SMALLINT     DEFAULT 1
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_familias_nombre_linea ON datum_inter.familias (nombre, linea_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_familias_linea ON datum_inter.familias (linea_id)")

        print("Creando tabla: unidades_medida")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.unidades_medida (
                id           SERIAL PRIMARY KEY,
                clave        VARCHAR(10)    NOT NULL,
                nombre       VARCHAR(50)    NOT NULL,
                factor_base  NUMERIC(10,4)  DEFAULT 1.0000
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_unidades_clave ON datum_inter.unidades_medida (clave)")

        print("Creando tabla: articulos")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.articulos (
                id               SERIAL PRIMARY KEY,
                familia_id       INT           NOT NULL REFERENCES datum_inter.familias(id),
                numero_articulo  INT           NOT NULL,
                descripcion      TEXT,
                ultimo_mov       DATE,
                unidad_medida_id INT           NOT NULL REFERENCES datum_inter.unidades_medida(id),
                costo_unitario   NUMERIC(10,2),
                contenido        NUMERIC(10,4),
                created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_articulos_numero ON datum_inter.articulos (numero_articulo)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_articulos_familia ON datum_inter.articulos (familia_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_articulos_unidad ON datum_inter.articulos (unidad_medida_id)")

        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_articulos_updated_at ON datum_inter.articulos;
            CREATE TRIGGER trg_articulos_updated_at
                BEFORE UPDATE ON datum_inter.articulos
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tabla: categorias_producto")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.categorias_producto (
                id         SERIAL PRIMARY KEY,
                nombre     VARCHAR(100) NOT NULL,
                parent_id  INT          REFERENCES datum_inter.categorias_producto(id),
                status     SMALLINT     DEFAULT 1
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_categorias_nombre_parent ON datum_inter.categorias_producto (nombre, parent_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_categorias_parent ON datum_inter.categorias_producto (parent_id)")

        print("Creando tabla: puntos_venta")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.puntos_venta (
                id         SERIAL PRIMARY KEY,
                nombre     VARCHAR(100) NOT NULL,
                status     SMALLINT     DEFAULT 1,
                created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_puntos_venta_nombre ON datum_inter.puntos_venta (nombre)")

        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_puntos_venta_updated_at ON datum_inter.puntos_venta;
            CREATE TRIGGER trg_puntos_venta_updated_at
                BEFORE UPDATE ON datum_inter.puntos_venta
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tabla: tipos_producto")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.tipos_producto (
                id             SERIAL PRIMARY KEY,
                nombre         VARCHAR(100) NOT NULL,
                status         SMALLINT     DEFAULT 1,
                punto_venta_id INT,
                created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_tipos_producto_nombre ON datum_inter.tipos_producto (nombre)")

        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_tipos_producto_updated_at ON datum_inter.tipos_producto;
            CREATE TRIGGER trg_tipos_producto_updated_at
                BEFORE UPDATE ON datum_inter.tipos_producto
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tabla: descuentos")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.descuentos (
                id               SERIAL PRIMARY KEY,
                nombre           VARCHAR(150) NOT NULL,
                status           SMALLINT     DEFAULT 1,
                punto_venta_id   INT          NOT NULL REFERENCES datum_inter.puntos_venta(id),
                tipo_producto_id INT          NOT NULL REFERENCES datum_inter.tipos_producto(id)
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_descuentos_nombre ON datum_inter.descuentos (nombre)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_descuentos_pv ON datum_inter.descuentos (punto_venta_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_descuentos_tp ON datum_inter.descuentos (tipo_producto_id)")

        print("Creando tabla: turnos")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.turnos (
                id          SERIAL PRIMARY KEY,
                nombre      VARCHAR(50) NOT NULL,
                hora_inicio TIME        NOT NULL,
                hora_fin    TIME        NOT NULL,
                created_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_turnos_nombre ON datum_inter.turnos (nombre)")

        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_turnos_updated_at ON datum_inter.turnos;
            CREATE TRIGGER trg_turnos_updated_at
                BEFORE UPDATE ON datum_inter.turnos
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tabla: subrecetas")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.subrecetas (
                id               SERIAL PRIMARY KEY,
                nombre           VARCHAR(150)  NOT NULL,
                rendimiento      NUMERIC(10,2),
                unidad_medida_id INT           NOT NULL REFERENCES datum_inter.unidades_medida(id),
                status           SMALLINT      DEFAULT 1,
                created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_subrecetas_nombre ON datum_inter.subrecetas (nombre)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_subrecetas_unidad ON datum_inter.subrecetas (unidad_medida_id)")

        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_subrecetas_updated_at ON datum_inter.subrecetas;
            CREATE TRIGGER trg_subrecetas_updated_at
                BEFORE UPDATE ON datum_inter.subrecetas
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tabla: subreceta_componentes")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.subreceta_componentes (
                id                  SERIAL PRIMARY KEY,
                subreceta_padre_id  INT           NOT NULL REFERENCES datum_inter.subrecetas(id) ON DELETE CASCADE,
                articulo_id         INT           REFERENCES datum_inter.articulos(id),
                subreceta_id        INT           REFERENCES datum_inter.subrecetas(id),
                cantidad            NUMERIC(10,3) NOT NULL,
                costo_parcial       NUMERIC(10,2),
                created_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_subreceta_componente CHECK (
                    (articulo_id IS NOT NULL AND subreceta_id IS NULL) OR
                    (articulo_id IS NULL AND subreceta_id IS NOT NULL)
                )
            )
        """)

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_subreceta_componentes 
            ON datum_inter.subreceta_componentes (subreceta_padre_id, 
                                                   COALESCE(articulo_id, 0), 
                                                   COALESCE(subreceta_id, 0))
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_subreceta_comp_articulo ON datum_inter.subreceta_componentes (articulo_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_subreceta_comp_sub ON datum_inter.subreceta_componentes (subreceta_id)")

        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_subreceta_componentes_updated_at ON datum_inter.subreceta_componentes;
            CREATE TRIGGER trg_subreceta_componentes_updated_at
                BEFORE UPDATE ON datum_inter.subreceta_componentes
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tabla: platillos")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.platillos (
                id                    SERIAL PRIMARY KEY,
                nombre                VARCHAR(150)  NOT NULL,
                categoria_id          INT           NOT NULL REFERENCES datum_inter.categorias_producto(id),
                costo_manual          NUMERIC(10,2),
                ingredientes          JSON,
                costo_calculado       NUMERIC(10,2),
                status                SMALLINT      DEFAULT 1,
                created_at            TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                updated_at            TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_platillos_nombre ON datum_inter.platillos (nombre)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_platillos_categoria ON datum_inter.platillos (categoria_id)")

        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_platillos_updated_at ON datum_inter.platillos;
            CREATE TRIGGER trg_platillos_updated_at
                BEFORE UPDATE ON datum_inter.platillos
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tabla: platillo_componentes")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.platillo_componentes (
                id                  SERIAL PRIMARY KEY,
                platillo_id         INT           NOT NULL REFERENCES datum_inter.platillos(id) ON DELETE CASCADE,
                articulo_id         INT           REFERENCES datum_inter.articulos(id),
                subreceta_id        INT           REFERENCES datum_inter.subrecetas(id),
                cantidad            NUMERIC(10,3) NOT NULL,
                costo_parcial       NUMERIC(10,2),
                created_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_platillo_componente CHECK (
                    (articulo_id IS NOT NULL AND subreceta_id IS NULL) OR
                    (articulo_id IS NULL AND subreceta_id IS NOT NULL)
                )
            )
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_platillo_componentes
            ON datum_inter.platillo_componentes (platillo_id,
                                                 COALESCE(articulo_id, 0),
                                                 COALESCE(subreceta_id, 0))
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_platillo_comp_articulo ON datum_inter.platillo_componentes (articulo_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_platillo_comp_sub ON datum_inter.platillo_componentes (subreceta_id)")
        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_platillo_componentes_updated_at ON datum_inter.platillo_componentes;
            CREATE TRIGGER trg_platillo_componentes_updated_at
                BEFORE UPDATE ON datum_inter.platillo_componentes
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("Creando tablas de ventas jerarquicas (sin tabla ventas intermedia)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.ventas_anuales (
                id              SERIAL PRIMARY KEY,
                punto_venta_id  INT           NOT NULL REFERENCES datum_inter.puntos_venta(id) ON DELETE RESTRICT ON UPDATE CASCADE,
                anio            SMALLINT      NOT NULL,
                subtotal        NUMERIC(14,2) DEFAULT 0.00,
                descuento       NUMERIC(14,2) DEFAULT 0.00,
                total           NUMERIC(14,2) DEFAULT 0.00,
                costo_total     NUMERIC(14,2) DEFAULT 0.00,
                utilidad_bruta  NUMERIC(14,2) DEFAULT 0.00,
                margen          NUMERIC(8,4)  DEFAULT 0.0000,
                created_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_venta_anual UNIQUE (punto_venta_id, anio)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ventas_anuales_pv ON datum_inter.ventas_anuales (punto_venta_id)")
        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_ventas_anuales_updated_at ON datum_inter.ventas_anuales;
            CREATE TRIGGER trg_ventas_anuales_updated_at
                BEFORE UPDATE ON datum_inter.ventas_anuales
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.ventas_mensuales (
                id               SERIAL PRIMARY KEY,
                venta_anual_id   INT           NOT NULL REFERENCES datum_inter.ventas_anuales(id) ON DELETE CASCADE ON UPDATE CASCADE,
                mes              SMALLINT      NOT NULL CHECK (mes BETWEEN 1 AND 12),
                subtotal         NUMERIC(14,2) DEFAULT 0.00,
                descuento        NUMERIC(14,2) DEFAULT 0.00,
                total            NUMERIC(14,2) DEFAULT 0.00,
                costo_total      NUMERIC(14,2) DEFAULT 0.00,
                utilidad_bruta   NUMERIC(14,2) DEFAULT 0.00,
                margen           NUMERIC(8,4)  DEFAULT 0.0000,
                created_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                updated_at       TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_venta_mensual UNIQUE (venta_anual_id, mes)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ventas_mensuales_anual ON datum_inter.ventas_mensuales (venta_anual_id)")
        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_ventas_mensuales_updated_at ON datum_inter.ventas_mensuales;
            CREATE TRIGGER trg_ventas_mensuales_updated_at
                BEFORE UPDATE ON datum_inter.ventas_mensuales
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datum_inter.ventas_diarias (
                id SERIAL PRIMARY KEY,
                venta_mensual_id INT NOT NULL REFERENCES datum_inter.ventas_mensuales(id) ON DELETE CASCADE,
                dia SMALLINT NOT NULL,
                fecha DATE NOT NULL,
                turno_manana JSONB,
                turno_tarde JSONB,
                encontrados JSONB DEFAULT '[]',
                no_encontrados JSONB DEFAULT '[]',
                descuentos JSONB DEFAULT '[]',
                subtotal NUMERIC(14,2) DEFAULT 0,
                descuento NUMERIC(14,2) DEFAULT 0,
                total NUMERIC(14,2) DEFAULT 0,
                costo_total NUMERIC(14,2) DEFAULT 0,
                utilidad_bruta NUMERIC(14,2) DEFAULT 0,
                margen NUMERIC(10,4) DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_venta_diaria UNIQUE (venta_mensual_id, dia)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ventas_diarias_mensual ON datum_inter.ventas_diarias (venta_mensual_id)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ventas_diarias_fecha ON datum_inter.ventas_diarias (fecha)")
        cursor.execute("""
            DROP TRIGGER IF EXISTS trg_ventas_diarias_updated_at ON datum_inter.ventas_diarias;
            CREATE TRIGGER trg_ventas_diarias_updated_at
                BEFORE UPDATE ON datum_inter.ventas_diarias
                FOR EACH ROW EXECUTE FUNCTION datum_inter.fn_set_updated_at()
        """)

        print("NOTA: Las tablas de ventas ya NO incluyen tabla 'ventas' independiente")
        print("      Todo se almacena directamente en ventas_diarias usando JSONB")

        crear_vista_resumen(cursor)

        print("Insertando turnos...")
        cursor.execute("""
            INSERT INTO datum_inter.turnos (nombre, hora_inicio, hora_fin) VALUES
                ('Mañana', '07:00:00', '13:59:00'),
                ('Tarde/Noche', '14:00:00', '03:00:00')
            ON CONFLICT (nombre) DO NOTHING
        """)

        print("Insertando puntos de venta...")
        puntos_venta = [
            (1, 'Mulligan NC', 1),
            (2, 'Restaurante Vista del Lago', 1),
            (3, 'Sushi', 1),
            (4, 'Callos de cortes', 1),
            (5, 'Hoyo 10', 1),
            (6, 'Carrito 1', 1),
            (7, 'Carrito 2', 1)
        ]

        for pv in puntos_venta:
            cursor.execute("""
                INSERT INTO datum_inter.puntos_venta (id, nombre, status) 
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, pv)

        cursor.execute(
            "SELECT setval('datum_inter.puntos_venta_id_seq', (SELECT MAX(id) FROM datum_inter.puntos_venta))")

        print("Insertando líneas...")
        lineas = [
            (1, 'AYB', 1), (2, 'CAMPO DE GOLF', 1), (3, 'CASA CLUB', 1),
            (4, 'MANTENIMIENTO', 1), (5, 'MATERIALES',
                                      1), (6, 'NAVE DE CARRITOS', 1),
            (7, 'PERFORMANCE LAB', 1), (8, 'SERVICIOS',
                                        1), (9, 'SUMINISTROS GENERALES', 1)
        ]

        for linea in lineas:
            cursor.execute("""
                INSERT INTO datum_inter.lineas (id, nombre, status) VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, linea)

        cursor.execute(
            "SELECT setval('datum_inter.lineas_id_seq', (SELECT MAX(id) FROM datum_inter.lineas))")

        print("Insertando familias...")
        familias = [
            (1, 'ABARROTES', 1), (2, 'AVES', 1), (3, 'BEBIDAS ALCOHOLICAS', 1),
            (4, 'BEBIDAS NO ALCOHOLICAS', 1), (5,
                                               'CARNES', 1), (6, 'CONGELADOS', 1),
            (7, 'DULCES Y PALETAS', 1), (8, 'EMBUTIDOS Y CARNES FRÍAS', 1),
            (9, 'FRUTAS Y VERDURAS', 1), (10, 'LACTEOS',
                                          1), (11, 'PESCADOS Y MARISCOS', 1),
            (12, 'TABACO', 1), (13, 'VINOS DE MESA', 1), (14, 'AGROQUIMICOS', 2),
            (15, 'ARTÍCULOS DE GOLF', 2), (16, 'COMBUSTIBLES',
                                           2), (17, 'EQUIPO / HERRAMIENTA / HERRAMIENTA MENOR', 2),
            (18, 'INSUMOS', 2), (19, 'MATERIALES', 2), (20, 'NAVE DE CARRITOS', 2),
            (21, 'REFACCIONES', 2), (22, 'SERVICIOS',
                                     2), (23, 'ARTÍCULOS DEPORTIVOS', 3),
            (24, 'ARTÍCULOS MÉDICOS', 3), (25,
                                           'EQUIPO DE GIMNASIO', 3), (26, 'EVENTOS', 3),
            (27, 'ALBERCA', 4), (28, 'EQUIPO', 4), (29, 'HERRAMIENTA', 4),
            (30, 'MATERIAL ELÉCTRICO', 4), (31, 'PINTURA', 4), (32, 'PLOMERIA', 4),
            (33, 'REFACCIONES', 4), (34, 'SERVICIOS', 4), (35, 'AGROQUIMICOS', 5),
            (36, 'COMBUSTIBLE', 5), (37, 'FERTILIZANTES Y SEMILLAS',
                                     5), (38, 'MANTENIMIENTO EQUIPO RIEGO', 5),
            (39, 'REFACCIONES MAQUINARIA Y EQUIPO MENOR', 5), (40, 'ACCESORIOS', 6),
            (41, 'BATERÍAS', 6), (42, 'CONSUMIBLES', 6), (43, 'HERRAMIENTA', 6),
            (44, 'REFACCIONES', 6), (45, 'ACCESORIOS DE GOLF',
                                     7), (46, 'CABEZAS / BASTONES', 7),
            (47, 'COMPONENTES DE ENSAMBLE', 7), (48,
                                                 'EQUIPO DE TALLER', 7), (49, 'GRIPS', 7),
            (50, 'HERRAMIENTAS DE TALLER', 7), (51,
                                                'VARILLAS', 7), (52, 'ARRENDAMIENTO', 8),
            (53, 'LAVANDERÍA', 8), (54, 'SERVICIOS',
                                    8), (55, 'ARTÍCULOS DE VENTA', 9),
            (56, 'CONSUMIBLES', 9), (57, 'EQUIPAMIENTO CASA CLUB',
                                     9), (58, 'EQUIPO RESTAURANT', 9),
            (59, 'PAPELERÍA', 9), (60, 'SOFTWARE',
                                   9), (61, 'SUMINISTROS DE LIMPIEZA', 9),
            (62, 'SUMINISTROS DE SISTEMAS', 9), (63, 'SUMINISTROS DESECHABLES', 9),
            (64, 'SUMINISTROS QUÍMICOS', 9)
        ]

        for familia in familias:
            cursor.execute("""
                INSERT INTO datum_inter.familias (id, nombre, linea_id, status) 
                VALUES (%s, %s, %s, 1)
                ON CONFLICT (id) DO NOTHING
            """, familia)

        cursor.execute(
            "SELECT setval('datum_inter.familias_id_seq', (SELECT MAX(id) FROM datum_inter.familias))")

        print("Insertando unidades de medida...")
        unidades = [
            (1, 'kg', 'Kilogramo', 1.0000), (2, 'lt', 'Litro', 1.0000),
            (3, 'ml', 'Mililitros', 1.0000), (4, 'gr', 'Gramos', 1.0000),
            (5, 'pz', 'Pieza', 1.0000), (7, 'mt', 'Metro', 1.0000),
            (8, 'srv', 'Servicio', 1.0000)
        ]

        for unidad in unidades:
            cursor.execute("""
                INSERT INTO datum_inter.unidades_medida (id, clave, nombre, factor_base) 
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, unidad)

        cursor.execute(
            "SELECT setval('datum_inter.unidades_medida_id_seq', (SELECT MAX(id) FROM datum_inter.unidades_medida))")

        print("Insertando categorías de producto...")
        categorias = [
            (1, 'BARRA', None), (2, 'Cafés', 1), (3, 'Te\'s', 1),
            (4, 'Bebidas Frías', 1), (5, 'Cockteles', 1), (6, 'Cervezas', 1),
            (7, 'Jugos', 1), (8, 'Vinos', 1), (9, 'Licores', 1),
            (10, 'Mezcladores Barra', 1), (11, 'Sub recetas jugos', 7),
            (12, 'Los especiales', 7), (13, 'Tintos', 8), (14, 'Blancos/Rosados/Espumosos', 8),
            (15, 'Brandy & Cognac', 9), (16,
                                         'Aperitivos', 9), (17, 'Ginebra y Vodka', 9),
            (18, 'Mezcal', 9), (19, 'Ron', 9), (20, 'Tequila', 9),
            (21, 'Whisky', 9), (22, 'DESAYUNOS', None), (23, 'Chilaquiles', 22),
            (24, 'Clásicos', 22), (25, 'Especialidades',
                                   22), (26, 'De la Granja', 22),
            (27, 'Fruta', 22), (28, 'Cereales y Panes',
                                22), (29, 'Buffete Desayuno', 22),
            (30, 'Huevos', 26), (31, 'COMIDAS/CENAS',
                                 None), (32, 'Antojitos Mexicanos', 31),
            (33, 'Entradas', 31), (34, 'Sopas', 31), (35, 'Pastas', 31),
            (36, 'Menús Especiales', 31), (37, 'Aves', 31), (38, 'Mariscos', 31),
            (39, 'Carnes Rojas', 31), (40, 'Clasicos', 31), (41, 'Enchiladas', 31),
            (42, 'Buffet Comida/Cena', 31), (43,
                                             'Burritos/Chapatas/Sandwiches', 31),
            (44, 'Hamburguesas/HotDogs', 31), (45,
                                               'Parrillada', 31), (46, 'Ensaladas', 31),
            (47, 'Botanas', 31), (48, 'Menú Infantil',
                                  31), (49, 'SUB RECETAS', None),
            (50, 'Platillos', 49), (51, 'Pastelería', 49), (52, 'EXTRAS', None),
            (53, 'Con costo', 52), (54, 'Sin costo', 52), (55, 'Modificadores', 52),
            (56, 'GUARNICIONES', None), (57, 'POSTRES', None), (58, 'TABACO', None),
            (59, 'SUSHI', None), (60, 'CALLOS CORTES', None), (61, 'SNACK', None),
            (62, 'Dulces', 57), (63, 'Entradas', 59), (64, 'Tostadas', 59),
            (65, 'Yakimeshi', 59), (66, 'Bowls',
                                    59), (67, 'Rollos tradicionales', 59),
            (68, 'Rollos especiales', 59), (69,
                                            'Rollos empanizados', 59), (70, 'Postres', 59),
            (71, 'Extras Sushi', 59), (72, 'Ramen y pastas',
                                       59), (73, 'Especialidades', 59),
            (74, 'Subrecetas Salsas', 59), (75,
                                            'Guarniciones Sushi', 59), (76, 'Ensaladas', 59),
            (77, 'Cócteles', 59), (78, 'Sashimi',
                                   59), (79, 'Sub recetas callos', 60),
            (80, 'Marisquería', 60), (81, 'A elegir', 80), (82, 'Ceviches', 80),
            (83, 'Tacos', 80), (84, 'Tostadas', 80), (85, 'Mariscadas', 80)
        ]

        for categoria in categorias:
            cursor.execute("""
                INSERT INTO datum_inter.categorias_producto (id, nombre, parent_id, status) 
                VALUES (%s, %s, %s, 1)
                ON CONFLICT (id) DO NOTHING
            """, categoria)

        cursor.execute(
            "SELECT setval('datum_inter.categorias_producto_id_seq', (SELECT MAX(id) FROM datum_inter.categorias_producto))")

        print("Insertando tipos de producto...")
        tipos = [
            (1, 'Vista Alimentos', 2), (2, 'Vista Bebidas con alcohol', 2),
            (3, 'Vista Bebidas sin alcohol', 2), (4, 'Mulligan Alimentos', 1),
            (5, 'Mulligan Bebidas con alcohol', 1), (6,
                                                     'Mulligan Bebidas sin alcohol', 1),
            (7, 'Sushi Alimentos', 3), (8, 'Sushi Bebidas con alcohol', 3),
            (9, 'Sushi Bebidas sin alcohol', 3), (10, 'Callos Alimentos', 4),
            (11, 'Callos Bebidas con alcohol',
             4), (12, 'Callos Bebidas sin alcohol', 4),
            (13, 'Carrito 1 Alimentos', 6), (14,
                                             'Carrito 1 Bebidas con alcohol', 6),
            (15, 'Carrito 1 Bebidas sin alcohol',
             6), (16, 'Carrito 2 Alimentos', 7),
            (17, 'Carrito 2 Bebidas con alcohol',
             7), (18, 'Carrito 2 Bebidas sin alcohol', 7),
            (19, 'Hoyo 10 Alimentos', 5), (20, 'Hoyo 10 Bebidas con alcohol', 5),
            (21, 'Hoyo 10 Bebidas sin alcohol', 5), (22, 'Tabaco', None),
            (23, 'Descuentos', None)
        ]

        for tipo in tipos:
            cursor.execute("""
                INSERT INTO datum_inter.tipos_producto (id, nombre, status, punto_venta_id) 
                VALUES (%s, %s, 1, %s)
                ON CONFLICT (id) DO NOTHING
            """, tipo)

        cursor.execute(
            "SELECT setval('datum_inter.tipos_producto_id_seq', (SELECT MAX(id) FROM datum_inter.tipos_producto))")

        print("Insertando descuentos...")
        descuentos = [
            (1, 'Descuento Mulligan', 1, 23), (2, 'Descuento Vista lago', 2, 23),
            (3, 'Descuento Sushi', 3, 23), (4, 'Descuento Callos', 4, 23),
            (5, 'Descuento Hoyo 10', 5, 23), (6, 'Descuento Carrito 1', 6, 23),
            (7, 'Descuento Carrito 2', 7, 23), (8, 'Descuento CS', 4, 23),
            (9, 'Descuento SU', 3, 23)
        ]

        for descuento in descuentos:
            cursor.execute("""
                INSERT INTO datum_inter.descuentos (id, nombre, status, punto_venta_id, tipo_producto_id) 
                VALUES (%s, %s, 1, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, descuento)

        cursor.execute(
            "SELECT setval('datum_inter.descuentos_id_seq', (SELECT MAX(id) FROM datum_inter.descuentos))")

        connexion.commit()

        print("=" * 70)
        print("Base de datos PostgreSQL inicializada")
        print("\nTABLAS CREADAS:")
        print(
            "   [CON DATOS]  → lineas, familias, unidades_medida, categorias_producto")
        print("                → puntos_venta, tipos_producto, descuentos, turnos")
        print(
            "   [SIN DATOS]  → articulos, subrecetas, subreceta_componentes, platillos")
        print("                → platillo_componentes, ventas_anuales, ventas_mensuales")
        print("                → ventas_diarias")
        print("\nESTRUCTURA DE VENTAS (jerárquica, SIN tabla 'ventas'):")
        print("   ventas_anuales → ventas_mensuales → ventas_diarias")
        print("   ventas_diarias contiene:")
        print("     - turno_manana (JSONB)")
        print("     - turno_tarde (JSONB)")
        print("     - encontrados (JSONB)  ← platillos encontrados")
        print("     - no_encontrados (JSONB) ← productos no encontrados")
        print("     - descuentos (JSONB) ← descuentos aplicados")
        print("\nREGISTROS INSERTADOS:")
        print(f"   - turnos: 2")
        print(f"   - puntos_venta: 7")
        print(f"   - lineas: 9")
        print(f"   - familias: 64")
        print(f"   - unidades_medida: 7")
        print(f"   - categorias_producto: 85")
        print(f"   - tipos_producto: 23")
        print(f"   - descuentos: 9")
        print("\nNOTA: Las tablas de articulos, recetas y platillos")
        print("      están creadas pero VACÍAS.")
        print("      Las ventas se cargan directamente en ventas_diarias.")
        print("=" * 70)

    except psycopg2.Error as e:
        print(f"❌ Error en PostgreSQL: {e}")
        if connexion:
            connexion.rollback()
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        if connexion:
            connexion.rollback()
    finally:
        if cursor:
            cursor.close()
        if connexion and not connexion.closed:
            connexion.close()


if __name__ == '__main__':
    initialize_database()
