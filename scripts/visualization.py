from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich import print as rprint

console = Console()

def print_kpi_summary(stats_prep, total_vlm_skus, rejected_skus):
    """Muestra un resumen ejecutivo de la ingesta de datos."""
    
    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    
    # Tabla Izquierda: Datos Totales
    t1 = Table(title="📂 Ingesta de Datos", border_style="blue")
    t1.add_column("Métrica", style="cyan")
    t1.add_column("Valor", style="white")
    t1.add_row("SKUs Maestros", str(stats_prep.total_skus_master))
    t1.add_row("SKUs con Ventas", str(stats_prep.total_skus_final))
    t1.add_row("Pedidos Procesados", str(stats_prep.orders_processed))
    
    # Tabla Derecha: Filtrado VLM (Lo que le importa al cliente)
    t2 = Table(title="🏭 Aptitud VLM (Filtros)", border_style="green")
    t2.add_column("Categoría", style="magenta")
    t2.add_column("SKUs", style="yellow")
    t2.add_row("Aptos (Peso < 1kg, Vol > 0)", str(total_vlm_skus))
    t2.add_row("Descartados (Pesados/Sin Data)", str(rejected_skus))
    
    grid.add_row(t1, t2)
    
    console.print(Panel(grid, title="[bold]Reporte de Inicialización - Slotting Bremen[/bold]", expand=False))

def print_tray_visual(tray_id, items, occupancy_pct):
    """Visualización ASCII de una bandeja."""
    color = "green" if occupancy_pct > 80 else "yellow" if occupancy_pct > 50 else "red"
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("SKU ID", width=12)
    table.add_column("Volumen (m3)", justify="right")
    table.add_column("Grupo Afinidad", justify="center")
    
    # Mostrar top 5 items
    for item in items[:5]:
        table.add_row(str(item.sku_id), f"{item.volume:.4f}", str(getattr(item, 'group_id', 'N/A')))
    
    if len(items) > 5:
        table.add_row("...", "...", "...")
        
    panel = Panel(
        table,
        title=f"📦 Bandeja #{tray_id}",
        subtitle=f"Ocupación: [{color}]{occupancy_pct:.1f}%[/{color}] - Items: {len(items)}",
        border_style=color
    )
    console.print(panel)