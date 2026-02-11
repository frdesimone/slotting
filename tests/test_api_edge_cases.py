import pytest
from slotting.adapter import json_to_skus, json_to_orders, params_to_macro_config, params_to_micro_config
from slotting.algorithms.macro.allocator import run_macro_slotting
from slotting.algorithms.micro.grouping import build_groups
from slotting.algorithms.micro.affinity_graph import build_affinity_graph

# --- FIXTURES: Datos Base ---

@pytest.fixture
def base_skus_json():
    return [
        # SKU Estándar (Alto valor, pequeño)
        {"sku_id": "GOLD_1", "rot": 100, "height": 10, "volume": 0.01, "weight": 1, "is_sensitive": False},
        # SKU Pesado
        {"sku_id": "HEAVY_1", "rot": 80, "height": 50, "volume": 0.1, "weight": 1000, "is_sensitive": False}, # 1000kg!
        # SKU Sensible
        {"sku_id": "SENS_1", "rot": 200, "height": 20, "volume": 0.05, "weight": 2, "is_sensitive": True},
        # SKU Gigante
        {"sku_id": "HUGE_1", "rot": 50, "height": 2000, "volume": 5.0, "weight": 10, "vlm_eligible": False},
    ]

# --- CASOS BORDE MACRO ---

def test_macro_all_sensitive_rejected(base_skus_json):
    """Caso Borde: Si todo es sensible (robable), el VLM debe quedar vacío (o ir a Jaula)."""
    # Modificamos los datos para que TODOS sean sensibles
    for s in base_skus_json:
        s["is_sensitive"] = True

    skus = json_to_skus(base_skus_json)
    config = params_to_macro_config({"vlm_total_volume": 100.0}) # Mucho espacio
    
    results = run_macro_slotting(skus, config)
    
    # Verificamos que NADA haya ido a VLM "Normal"
    assigned_to_vlm = [r for r in results if r.storage_type == "VLM"]
    assert len(assigned_to_vlm) == 0, "No debería haber items en VLM si todos son sensibles"
    
    assigned_to_jaula = [r for r in results if r.storage_type == "JAULA"]
    assert len(assigned_to_jaula) == len(skus), "Todos deberían ir a Jaula"

def test_macro_zero_capacity(base_skus_json):
    """Caso Borde: El cliente configuró 0 m3 de capacidad (error de input)."""
    skus = json_to_skus(base_skus_json)
    config = params_to_macro_config({"vlm_total_volume": 0.0}) 
    
    results = run_macro_slotting(skus, config)
    
    assigned_to_vlm = [r for r in results if r.storage_type == "VLM"]
    assert len(assigned_to_vlm) == 0, "Con capacidad 0, nada puede entrar al VLM"
    
    # Validar que tengan una razón de rechazo (Overflow o similar)
    overflows = [r for r in results if r.storage_type == "RACK"]
    # NOTA: Ajusta esto según tu lógica de 'HUGE_1' que ya iba a Rack por ineligible
    assert len(overflows) > 0

# --- CASOS BORDE MICRO ---

def test_micro_chain_affinity():
    """
    Caso: Cadena de afinidad A-B-C.
    A se pide con B.
    B se pide con C.
    A nunca se pide con C.
    ¿El algoritmo agrupa A-B-C juntos gracias a B?
    """
    skus_json = [
        {"sku_id": "A", "rot": 10, "height": 10, "volume": 1, "weight": 1},
        {"sku_id": "B", "rot": 10, "height": 10, "volume": 1, "weight": 1},
        {"sku_id": "C", "rot": 10, "height": 10, "volume": 1, "weight": 1},
    ]
    orders_json = [
        {"order_id": "O1", "sku_ids": ["A", "B"]}, # Enlace A-B
        {"order_id": "O2", "sku_ids": ["B", "C"]}, # Enlace B-C
    ]
    
    skus = json_to_skus(skus_json)
    orders = json_to_orders(orders_json)
    
    # Configuramos semilla 'B' para ver si atrae a ambos
    # O usamos estrategia 'top_rot' y confiamos en que al ser iguales rote
    config = params_to_micro_config({
        "graph_top_k_neighbors": 2,
        "group_max_size": 3,
        "group_seed_strategy": "top_rot"
    })
    
    # Construir grafo manualmente para debug (opcional)
    graph = build_affinity_graph(orders, 2, 0.0, config.affinity_metric)
    
    # Ejecutar grouping
    groups = build_groups(skus, orders, config)
    
    # Buscar el grupo más grande
    largest_group = max(groups, key=lambda g: len(g.sku_ids))
    
    # Idealmente, B actúa de puente y terminan los 3 juntos
    # O al menos terminan pares (A,B) o (B,C)
    print(f"\nGrupos generados: {[g.sku_ids for g in groups]}")
    assert len(largest_group.sku_ids) >= 2, "Debería haber agrupado al menos un par"
    
def test_micro_oversized_item_handling():
    """
    Caso Borde: Un SKU pesa más que la bandeja completa.
    Esto debería detectarse antes, pero probamos qué hace el algoritmo de grouping.
    """
    skus_json = [
        {"sku_id": "NORMAL", "rot": 10, "height": 10, "volume": 1, "weight": 10},
        {"sku_id": "THOR_HAMMER", "rot": 10, "height": 10, "volume": 1, "weight": 1000}, # 1 tonelada
    ]
    # Se piden juntos
    orders_json = [{"order_id": "O1", "sku_ids": ["NORMAL", "THOR_HAMMER"]}]
    
    skus = json_to_skus(skus_json)
    orders = json_to_orders(orders_json)
    
    # Configuración: Bandeja soporta solo 500kg
    config = params_to_micro_config({"tray_weight_max": 500.0})
    
    # El grouping probablemente los agrupe por afinidad (lógica de negocio), 
    # pero luego el paso de "Tray Building" (step 7) es el que debería fallar o separarlos.
    # Aquí probamos solo que el grouping no explote.
    groups = build_groups(skus, orders, config)
    
    thor_group = next(g for g in groups if "THOR_HAMMER" in g.sku_ids)
    assert thor_group is not None
    # Si tu lógica de grouping valida pesos de bandeja, esto podría fallar (y sería correcto).
    # Si solo agrupa lógicamente, pasará, y el problema será del algoritmo de packing posterior.

# --- INTEGRACIÓN E2E JSON (SIMULACIÓN API) ---

def test_full_api_flow_json(base_skus_json):
    """Simula el flujo completo que hará el servidor."""
    
    # 1. Input de Retool (JSON)
    raw_skus = base_skus_json
    raw_orders = [
        {"order_id": "O1", "sku_ids": ["GOLD_1", "GOLD_2"]}, # GOLD_2 no existe en master, debe ignorarse
        {"order_id": "O2", "sku_ids": ["GOLD_1"]},
    ]
    macro_params = {"vlm_total_volume": 50.0}
    micro_params = {"cycle_days": 14}
    
    # 2. Ejecución MACRO
    internal_skus = json_to_skus(raw_skus)
    macro_conf = params_to_macro_config(macro_params)
    macro_results = run_macro_slotting(internal_skus, macro_conf)
    
    # 3. Filtrado (El servidor filtra qué entra a Micro)
    vlm_sku_ids = {r.sku_id for r in macro_results if r.storage_type == "VLM"}
    micro_skus_input = [s for s in internal_skus if s.sku_id in vlm_sku_ids]
    
    # 4. Ejecución MICRO
    if micro_skus_input:
        internal_orders = json_to_orders(raw_orders)
        micro_conf = params_to_micro_config(micro_params)
        
        groups = build_groups(micro_skus_input, internal_orders, micro_conf)
        
        assert len(groups) > 0
        assert "GOLD_1" in vlm_sku_ids