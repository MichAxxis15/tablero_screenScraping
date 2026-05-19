# Pipeline de Scraping y Reportes
Sistema automatizado de extracción de datos desde el ERP DATUM (datumparaiso.com), con carga a una base de datos MySQL local, diseñado para alimentar reportes en Jaspersoft Studio.

## Tabla de Contenidos
- [Descripción General](#descripción-general)
- [Arquitectura del Proyecto](#arquitectura-del-proyecto)
- [Requisitos Previos](#requisitos-previos)
- [Instalación](#instalación)
- [Configuración del Archivo .env](#configuración-del-archivo-env)
- [Estructura de la Base de Datos](#estructura-de-la-base-de-datos)
- [Estructura del Excel de Recetas](#estructura-del-excel-de-recetas)
- [Descripción de Módulos](#descripción-de-módulos)
- [Ejecución del Pipeline](#ejecución-del-pipeline)
- [Catálogos y Datos iniciales](#catalogos-y-datos-inaiciales)
- [Integración con Jaspersoft Studio](#integración-con-jaspersoft-studio)
- [Solución de Problemas Comunes](#solución-de-problemas-comunes)
- [Consideraciones de Mantenimiento](#consideraciones-de-mantenimiento)
## Descripción General
Este proyecto extrae información del sistema POS/ERP DATUM mediante web scraping con Playwright, la procesa y la almacena en una base de datos MySQL relacional. El objetivo principal es generar una fuente de datos estructurada y limpia para reportes de **costos, utilidades y ventas por punto de venta** consumibles desde Jaspersoft Studio.

El pipeline ejecuta 4 pasos en secuencia:

[DATUM Web] → Scraping → [MySQL Local] ← Recetas (Excel) → [Jaspersoft Sudio]
## Arquitectura del Proyecto
```text
proyecto/
├── main.py             # Orquestador principal del pipeline
├── init_db.py          # Inicialización y creación del esquema de base de datos
├── articulos.py        # Scraper del reporte de existencias (inventario)
├── carga.py            # Cargador de recetas desde archivo Excel
├── ventas_res.py       # Scraper del reporte de ventas por producto
├── recetas/
│   └── recetas.xlsx    # Archivo Excel con subrecetas, platillos y bebidas
├── articulos/          # Carpeta generada automáticamente con respaldos en Excel
├── .env                # Variables de entorno (credenciales y configuración)
├── requirements.txt    # Dependencias Python
└── README.md           # Este archivo
```
## Requisitos Previos
- **Python** 3.10 o superior
- **MySQL** 8.0 o superior (corriendo localmente o en red)
- **Google Chrome** o **Chromium** (usado por Playwright)
- **Jaspersoft Studio** (para consumir los reportes, instalación separada)
- Acceso a Internet y credenciales válidas en [datumparaiso.com](https://datumparaiso.com)
## Instalación
1. Clonar o descargar el proyecto
```bash
git clone https://github.com/MichAxxis15/screenScraping datum_inter
cd datum_inter
```
2. Crear entorno virtual (recomendado)
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```
3. Instalar dependencias Python
```bash
pip install -r requirements.txt
```
Contenido de [requirements.txt](./requirements.txt):
```bash
playwright
bs4
pandas
pymsql
datetime
dotenv
openpyxl
mysql-connector-python
rich
```
4. Instalar navegadores de Playwright

Playwright necesita descargar los binarios del navegador por separado:
```bash
playwright install chromium
```
5. Crear la base de datos en MySQL

Conectarse a MySQL y crear la base de datos vacía (el script la llenará automáticamente):
```sql
CREATE DATABASE datum_inter CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```
> **IMPORTANTE** La base de datos debe existir pero estar vacía. [init_db.py](./init_db.py) detecta si no hya tablas y crea el esquema completo con datos iniciales de forma automática. Si ya tiene tablas, las omite.

## Configuración del Archivo .env
Crear un archivo llamado <code>.env</code> en la raíz del proyecto con el siguiente contenido:
```bash
# -- Credenciales DATUM -------------
LOGIN_URL=
DATUM_USER=
DATUM_PASSWORD=

# -- URLs de reportes DATUM --------------
REP_EXIS_URL=
REP_VENT_PROD=

# -- Periodo a procesar (formato DD/MM/AAAA) ---------------------
FECHA_INICIO=
FECHA_FIN=

# -- Conexión MySQL ---------------
DB_HOST=
DB_PORT=
DB_USER=
DB_PASSWORD=
DB_NAME=
```

### Descripción de cada variable

| Variable | Descripción |
| :--- | ---: |
| LOGIN_URL | URL del formulario de login de DATUM |
| DATUM_USER | Usuario de acceso al sistema DATUM | 
| DATUM_PASSWORD | Contraseña del sistema DATUM |
| REP_EXIS_URL | URL del reporte de existencias de inventario | 
| REP_VENT_PROD | URL del reporte de ventas por producto |
| FECHA_INICIO | Fecha de inicio del periodo a extraer (DD/MM/AAAA) |
| FECHA_FIN | Fecha de fin del periodo a extraer (DD/MM/AAAA) |
| DB_HOST | Host del servidor MySQL | 
| DB_PORT | Puerto MySQL |
| DB_USER | Usuario MySQL |
| DB_PASSWORD | Contraseña MySQL |
| DB_NAME | Nombre de la base de datos |

> **Seguridad**: Nunca subir el archivo <code>.env</code> a un repositorio público. Agregar <code>.env</code> al <code>.gitignore</code>.
## Estructura de la Base de Datos
El esquema se crea automáticamente la primera vez que se ejecuta el proyecto. Las tablas principales son:
### Catálogos (datos de referencia)
| Tabla | Descripción |
| :--- | ---: |
| lineas | Líneas de productos del inventario DATUM (ej. Alimentos, Bebidas) |
| familias | Subfamilias dentro de cada línea |
| unidades_medida | Unidades: <code>kg</code>,<code>lt</code>,<code>ml</code>,<code>gr</code>,<code>pz</code>,<code>mt</code>,<code>srv</code> |
| categorias_producto | Categorías de platillos (Desayunos, Comidas, Bebidas, etc.) con soporte de jerarquía |
| turnos | Turno Mañana (7:00-13:59) y Turno Tarde/Noche (14:00-03:00) |
| tipos_producto | Puntos de venta + tipo de producto (ej. "Vista Alimentos", "Sushi Bebidas con alcohol") |
|puntos_venta | Áreas/sucursales de venta registradas en DATUM |
| descuentos | Descuentos por nombre y punto de venta |
### Inventario y Recetas
| Tabla | Descripción |
| :--- | ---: |
| articulos | Insumos/materias primas obtenidos del inventario DATUM |
| subrecetas | Preparaciones intermedias reutilizables (ej. salsas, bases) |
| subreceta_componentes | Ingredientes de cada subreceta (artículos u otras subrecetas) |
| platillos | Productos del menú (platillos y bebidas) |
| paltillo_componentes | Ingredientes de cada platillo (artículos o subrecetas) |
### Ventas
| Tabla | Descripción |
| :--- | ---: |
| ventas | Encabezado de venta: punto de venta, turno, periodo, totales agregados |
| ventas_platillo | Detalle de ventas por platillo: cantidad, total, costo, utilidad, margen |
| ventas_descuentos | Descuentos aplicados por venta |
| ventas_no_encontrados | Productos vendidos que no se encontraron en el catálogo de platillos |
### Relaciones clave
```bash
lineas → familias → articulos
categorias_producto → platillos → platillo_componentes → articulos / subrecetas
puntos_venta + turnos → ventas → ventas_platillo → platillos
```
## Estructura del Excel de Recetas
El archivo [recetas/recetas.xlsx](./recetas/recetas.xlsx) debe tener tres hojas con nombres exactos:

### **Hoja <code>Sub</code> - Subrecetas** 
Preparaciones intermedias (bases, salsas, etc.) usadas como ingredientes en platillos.
| Columna | Descripción |
| :--- | ---: |
| producto | Nombre de la subreceta |
| ingrediente | Nombre del ingrediente (si es otra subreceta) |
| artículo | Número de artículo del inventario DATUM (si es insumo directo) |
| cantidad | Cantidad del ingrediente |
| u.medida | Unidad de medida del ingrediente |
| merma | Porcentaje de merma a aplicar (ej. <code>10</code> = 10%)

### **Hoja <code>Platillos</code> - Platillos del menú**
| Columna | Descripción |
| :--- | ---: |
| producto | Nombre del platillo |
| grupo | Categoría (debe existir en categorías_producto) |
| ingrediente | Nombre del ingrediente | (subreceta) |
| articulo | Número de artículo DATUM |
| cantidad | Cantidad |
| u.medida | Unidad de medida |
| merma | Porcentaje de merma |
### **Hoja <code>Bebidas</code> - Bebidas del menú**
Misma estructura que la hoja <code>Platillos</code>.

#### **Notas importantes sobre el Excel**
- La columna <code>producto</code> puede dejarse vacía en las filas subsecuentes de un mismo producto; el sistema aplica <code>ffill</code> (relleno hacia adelante) automáticamente.
- Los valores de <code>artículo</code> deben coincidir exactamente con los <code>numero_articulos</code> en la tabla <code>articulos</code>.
- Los nombres en <code>ingrediente</code> (para subrecetas) deben coincidir exactamente con los nombre en la hoja <code>Sub</code>.
- Las unidades en <code>u.medida</code> se normalizan automáticamnete: <code>ml</code>→
<code>lt</code>, <code>gr</code>→<code>kg</code>, etc.
- La merma se aplica con la fórmula: <code>cantidad_final = cantidad x (1 + merma / 100)</code>.
## Descripción de Módulos
## Ejecución del Pipeline
## Catálogos y Datos Iniciales
## Integración con Jaspersoft Studio
## Solución de Problemas Comunes
## Consideraciones de Mantenimiento
