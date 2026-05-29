import pytest
from slotting.adapter import json_to_skus, json_to_orders, params_to_macro_config as headers_to_macro_config, params_to_micro_config as headers_to_micro_config
from slotting.algorithms.macro.allocator import run_macro_slotting
from slotting.algorithms.micro.grouping import build_groups
from slotting.algorithms.micro.optimization.optimizer import optimize, LocalSearchConfig, HybridKpiState
from slotting.algorithms.micro.affinity_graph import build_affinity_graph

# --- DATOS DE PRUEBA (JSON MOCK) ---

MOCK_SKUS_JSON = [
    # Artículos de ALTA rotación (Candidatos VLM ideales)
    {"sku_id": "SKU_A1", "rot": 100, "height": 10, "volume": 0.01, "weight": 1, "cycle_units": 50, "vlm_eligible": True, "is_sensitive": False},
    {"sku_id": "SKU_A2", "rot": 90,  "height": 15, "volume": 0.02, "weight": 2, "cycle_units": 40, "vlm_eligible": True, "is_sensitive": False},
    
    # Artículo SENSIBLE (Hard Block -> Jaula)
    {"sku_id": "SKU_SENS", "rot": 200, "height": 10, "volume": 0.01, "weight": 1, "cycle_units": 100, "vlm_eligible": True, "is_sensitive": True},
    
    # Artículo NO APTO VLM (Hard Block -> Rack)
    {"sku_id": "SKU_BIG", "rot": 150, "height": 1000, "volume": 2.0, "weight": 50, "cycle_units": 10, "vlm_eligible": False, "is_sensitive": False},
    
    # Artículos BAJA rotación (Candidatos a relleno o exclusión si falta lugar)
    {"sku_id": "SKU_C1", "rot": 1, "height": 10, "volume": 0.01, "weight": 1, "cycle_units": 10, "vlm_eligible": True, "is_sensitive": False},
]

MOCK_ORDERS_JSON = [
    {"order_id": "O1", "sku_ids": ["SKU_A1", "SKU_A2"]}, # Afinidad fuerte A1-A2
    {"order_id": "O2", "sku_ids": ["SKU_A1", "SKU_A2"]},
    {"order_id": "O3", "sku_ids": ["SKU_A1"]},
    {"order_id": "O4", "sku_ids": ["SKU_SENS"]}, 
]

# --- TEST MACRO SLOTTING ---

def test_api_macro_execution():
    """Simula una petición al endpoint /run-macro"""
    
    # 1. Recibir Payload (JSON) y Headers
    payload_skus = MOCK_SKUS_JSON
    headers = {
        "vlm_total_volume": 10.0, # 10 m3 disponibles
        "vlm_occupancy": 0.90
    }
    
    # 2. Adaptar (Layer de API)
    internal_skus = json_to_skus(payload_skus)
    config = headers_to_macro_config(headers)
    
    # 3. Ejecutar Lógica
    results = run_macro_slotting(internal_skus, config)
    
    # 4. Validar Resultados (Response)
    results_map = {r.sku_id: r.storage_type for r in results}
    
    # Validaciones de Negocio
    assert results_map["SKU_SENS"] == "JAULA", "El flag is_sensitive debe enviar a JAULA aunque rote mucho"
    assert results_map["SKU_BIG"] == "RACK", "El flag vlm_eligible=False debe enviar a RACK"
    assert results_map["SKU_A1"] == "VLM", "SKU A1 debería entrar al VLM"

# --- TEST MICRO SLOTTING ---

def test_api_micro_execution():
    """Simula una petición al endpoint /run-micro"""
    
    # 1. Recibir Payload
    # Nota: Micro solo debe recibir los SKUs que Macro ya asignó al VLM.
    # Simulamos ese filtro aquí:
    vlm_skus_json = [s for s in MOCK_SKUS_JSON if s["sku_id"] in ["SKU_A1", "SKU_A2", "SKU_C1"]]
    orders_json = MOCK_ORDERS_JSON
    
    headers = {
        "cycle_days": 7,
        "group_max_size": 10,
        "affinity_metric": "jaccard"
    }
    
    # 2. Adaptar
    skus = json_to_skus(vlm_skus_json)
    orders = json_to_orders(orders_json)
    config = headers_to_micro_config(headers)
    
    # 3. Pipeline de Micro (Simplificado para test)
    # 3.a Construir Grafo
    graph = build_affinity_graph(orders, config.graph_top_k_neighbors, config.graph_aff_min, config.affinity_metric)
    
    # 3.b Agrupar (Clustering Greedy)
    groups = build_groups(skus, orders, config)
    
    # Validación intermedia: A1 y A2 deberían estar juntos
    a1_group = next(g for g in groups if "SKU_A1" in g.sku_ids)
    assert "SKU_A2" in a1_group.sku_ids, "La afinidad fuerte debe agrupar A1 y A2"
    
    # 3.c Optimizar (Simulación rápida)
    # Necesitamos convertir los AffinityGroup a Subgroups (si tu lógica interna lo requiere)
    # Aquí asumimos que tienes una forma de inicializar el State. Si no, testeamos solo hasta grouping.
    
    assert len(groups) > 0
    print(f"\nMicro Slotting generado {len(groups)} grupos.")