import sys
import logging

from rich.logging import RichHandler
from rich.console import Console

from init_db import initialize_database, crear_vista_resumen
import articulos
import carga
import ventas_screen

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)]
)

console = Console()


def execute_pipeline():
    try:
        console.rule(
            "[bold cyan]INICIANDO PIPELINE DATUM SCRAPPING[/bold cyan]")

        console.rule(
            "[bold blue]PASO 1: Inicializando Base de Datos[/bold blue]")
        with console.status("[yellow] Verificando base de datos...", spinner="dots"):
            initialize_database()
        logging.info("[green]✅ Base de Datos lista.[/green]\n")

        console.rule(
            "[bold blue]PASO 2: Extrayendo Artículos desde DATUM[/bold blue]")
        with console.status("[yellow]Ejecutando scrapper de articulos...", spinner="dots"):
            articulos.main()
        logging.info(
            "[green]✅ Artículos actualizados correctamente.[/green]\n")

        console.rule("[bold blue]PASO 3: Cargando Recetas[/bold blue]")
        with console.status("[yellow]Procesando archivo excel de recetas...", spinner="dots"):
            carga.main()
        logging.info("[green]✅ Recetas cargadas.[/green]\n")

        console.rule(
            "[bold blue]PASO 4: Procesando Resumen de Ventas[/bold blue]")
        with console.status("[yellow]Ejecutando scraper de ventas...", spinner="dots"):
            ventas_screen.main()
        logging.info("[green]✅ Proceso de ventas finalizado.[/green]\n")

        console.rule(
            "[bold blue]PASO 5: Creando Vista de Resumen por Punto de Venta[/bold blue]")
        with console.status("[yellow]Generando vista v_resumen_punto_venta...", spinner="dots"):
            crear_vista_resumen()
        logging.info("[green]✅ Vista de resumen creada.[/green]\n")

        console.rule(
            "[bold green]🚀 PIPELINE COMPLETADO CON ÉXITO[/bold green]")

    except Exception as e:
        logging.error(f"❌ ERROR CRÍTICO durante la ejecución: {e}")
        sys.exit(1)


if __name__ == "__main__":
    execute_pipeline()
