"""
Módulo de visualización para demos de Slotting.
Usa la librería 'rich' para tablas, paneles y barras de progreso.
"""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.progress import BarColumn, Progress, TextColumn
from rich import print as rprint
from collections import Counter

console = Console()

def print_step_header(title: str):
    console.print(f"\n[bold cyan]--- {title} ---[/bold cyan]")

def print_kpi_summary(skus, orders, stats):
    """Muestra un resumen ejecutivo de la ingesta de datos."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    
    # Tabla Izquierda: Datos Totales
    t1 = Table(title="📂 Ingesta de Datos", border_style="blue")
    t1.add_column("Métrica", style="cyan")
    t1.add_column("Valor", style="white")
    
    total_skus = len(skus)
    t1.add_row("SKUs Finales", str(total_skus))
    
    processed_orders = len(orders) if orders else "N/A"
    t1.add_row("Pedidos Activos", str(processed_orders))
    
    # Tabla Derecha: Validaciones
    t2 = Table(title="🔍 Validación", border_style="green")
    t2.add_column("Check", style="magenta")
    t2.add_column("Estado", style="yellow")
    
    if total_skus > 0:
        with_vol = sum(1 for s in skus if getattr(s, 'volume', 0) > 0)
        t2.add_row("Con Volumen", f"{with_vol} ({with_vol/total_skus:.1%})")
        
        with_weight = sum(1 for s in skus if getattr(s, 'weight', 0) > 0)
        t2.add_row("Con Peso", f"{with_weight} ({with_weight/total_skus:.1%})")
    else:
        t2.add_row("Con Volumen", "0 (0%)")
        t2.add_row("⚠️ ALERTA", "[bold red]SIN DATOS[/bold red]")
    
    grid.add_row(t1, t2)
    console.print(Panel(grid, title="[bold]Reporte de Inicialización[/bold]", expand=False))

def print_macro_results(results, vlm_total_vol, vlm_occupancy_target):
    """Visualización de resultados Macro (Allocator)."""
    counts = Counter(r.storage_type for r in results)
    vlm_assigned_volume = sum(r.cycle_volume for r in results if r.storage_type == "VLM")
    
    # 1. Tabla de Distribución
    t_dist = Table(title="📊 Distribución Macro (Almacén Completo)")
    t_dist.add_column("Tipo Almacenamiento", style="cyan")
    t_dist.add_column("Cant. SKUs", style="magenta", justify="right")
    t_dist.add_column("% SKUs", style="green", justify="right")

    total_skus = len(results)
    if total_skus == 0:
        console.print("[red]No hay resultados para mostrar[/red]")
        return

    for store_type, count in counts.items():
        t_dist.add_row(store_type, str(count), f"{(count/total_skus)*100:.1f}%")
    
    console.print(t_dist)

    # 2. Panel de Uso VLM
    target_vol = vlm_total_vol * vlm_occupancy_target
    fill_pct = (vlm_assigned_volume / target_vol) * 100 if target_vol > 0 else 0
    
    color = "green" if 80 <= fill_pct <= 100 else "yellow" if fill_pct < 80 else "red"
    
    # Barra de progreso manual
    bar_width = 30
    filled = int((fill_pct / 100) * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)

    summary_text = Text()
    summary_text.append(f"\nVolumen Ocupado: {vlm_assigned_volume:.2f} m3\n", style="white")
    summary_text.append(f"Capacidad Objetivo: {target_vol:.2f} m3\n", style="dim")
    summary_text.append(f"Llenado: [{bar}] {fill_pct:.1f}%", style=f"bold {color}")

    console.print(Panel(summary_text, title="🚀 Performance VLM (Volumétrico)", border_style=color))

def print_micro_results_final(all_trays, skus_total_count):
    """
    Panel final de resultados Micro-Slotting.
    Muestra KPIs de eficiencia y uso de bandejas.
    """
    if not all_trays:
        console.print("[red]No se generaron bandejas.[/red]")
        return

    total_trays = len(all_trays)
    
    # Calcular promedios
    avg_occupancy = sum(t.occupancy_percent for t in all_trays) / total_trays
    # Asumimos que tray tiene .weight_kg o calculamos sumando items
    total_weight_used = sum(sum(i.weight for i in t.items) for t in all_trays)
    # Capacidad teórica (hardcoded o del config, asumimos 750kg por bandeja std o leemos del objeto si tiene)
    # Para visualización rápida usamos un estimado si no está en el objeto tray
    tray_capacity_kg = getattr(all_trays[0], 'max_weight', 250.0) # Default 250kg
    total_capacity_kg = total_trays * tray_capacity_kg
    weight_pct = (total_weight_used / total_capacity_kg) * 100 if total_capacity_kg > 0 else 0

    # Layout Principal
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)

    # Panel Izquierdo: Métricas Duras
    t_stats = Table(show_header=False, box=None)
    t_stats.add_row("[bold cyan]Total Bandejas Generadas:[/bold cyan]", f"[bold white]{total_trays}[/bold white]")
    t_stats.add_row("[bold cyan]SKUs Ubicados:[/bold cyan]", f"[bold white]{skus_total_count}[/bold white]")
    t_stats.add_row("[bold cyan]Ocupación Promedio (Vol):[/bold cyan]", f"[bold yellow]{avg_occupancy:.1f}%[/bold yellow]")
    
    # Panel Derecho: Barras de Eficiencia
    t_bars = Table(show_header=False, box=None)
    
    # Barra Volumen
    vol_color = "green" if avg_occupancy > 70 else "yellow"
    t_bars.add_row("Espacio", _make_bar(avg_occupancy, color=vol_color))
    
    # Barra Peso
    weight_color = "green" if weight_pct > 50 else "blue" # Peso suele ser bajo en VLM
    t_bars.add_row("Peso", _make_bar(weight_pct, color=weight_color))

    grid.add_row(Panel(t_stats, title="Resumen Operativo"), Panel(t_bars, title="Eficiencia de Recursos"))
    
    console.print(Panel(grid, title="[bold]🏁 Resultados Finales Micro-Slotting[/bold]", border_style="green"))

    # Mostrar la "Mejor Bandeja"
    best_tray = max(all_trays, key=lambda t: t.occupancy_percent)
    print_micro_tray(best_tray, best_tray.items, detailed=True)

def _make_bar(pct, width=20, color="green"):
    """Helper para crear barrita de texto"""
    filled = int((pct / 100) * width)
    filled = min(filled, width) # Clamp
    bar = "█" * filled + "░" * (width - filled)
    return f"[{color}]{bar}[/{color}] {pct:.1f}%"

def print_micro_tray(tray, items, detailed=False):
    """Visualiza una bandeja individual con detalle."""
    occ = tray.occupancy_percent if hasattr(tray, 'occupancy_percent') else 0.0
    color = "green" if occ > 80 else "yellow" if occ > 50 else "red"
    
    # Header de la bandeja
    console.print(f"\n[bold]📦 Detalle de Bandeja (ID: {getattr(tray, 'id', 'N/A')})[/bold]")
    console.print(f"   Ocupación Volumétrica: [{color}]{occ:.1f}%[/{color}]")
    console.print(f"   Items contenidos: {len(items)}")
    
    # Tabla de Items
    t = Table(show_header=True, header_style="bold magenta", expand=True, border_style="dim")
    t.add_column("SKU ID", width=15, style="cyan")
    t.add_column("Volumen (m3)", justify="right")
    t.add_column("Peso (kg)", justify="right")
    t.add_column("Afinidad (Grp)", justify="center")
    
    # Mostrar top items
    limit = 10 if detailed else 5
    # Ordenar por volumen para mostrar los "grandes" primero
    sorted_items = sorted(items, key=lambda x: x.volume, reverse=True)
    
    for item in sorted_items[:limit]:
        grp = getattr(item, 'group_id', '-')
        w = getattr(item, 'weight', 0.0)
        t.add_row(
            str(item.sku_id), 
            f"{item.volume:.5f}", 
            f"{w:.2f}",
            str(grp)
        )
    
    if len(items) > limit:
        t.add_row(f"... y {len(items)-limit} más", "-", "-", "-")

    console.print(t)
    console.print(f"[dim]Nota: Mostrando los items de mayor volumen primero.[/dim]\n")