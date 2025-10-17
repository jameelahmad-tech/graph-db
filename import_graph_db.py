import json
import os
from falkordb import FalkorDB
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Configuration

JSON_FILE = "clean_graphs_2nd.json"
HOST = "localhost"
PORT = 6379
BATCH_SIZE = 100
MAX_WORKERS = 4

# Schema definitions
NODE_TYPES = ["Person", "Organization", "Concept", "Event", "Object", "Attribute", "Location"]
NODE_PROPERTIES = ["id", "name", "type", "confidence", "created_at"]
EDGE_PROPERTIES = ["id", "type", "source_id", "target_id", "confidence", "created_at"]

print_lock = Lock()

def safe_print(msg):
    with print_lock:
        print(msg)


# DATA EXTRACTION (Simple & Schema-based)

def get_value(data, key):
    """Get value from data, checking both top-level and properties"""
    # Check top level
    if key in data and data[key] is not None:
        return data[key]
    
    # Check in properties
    if "properties" in data and isinstance(data["properties"], dict):
        if key in data["properties"] and data["properties"][key] is not None:
            return data["properties"][key]
    
    return None

def prepare_node(node):
    """Extract node data according to schema"""
    node_data = {}
    
    # Extract schema-defined properties
    for prop in NODE_PROPERTIES:
        value = get_value(node, prop)
        if value is not None:
            node_data[prop] = value
    
    # Set defaults if missing
    if "name" not in node_data:
        node_data["name"] = "unknown"
    if "type" not in node_data:
        node_data["type"] = "Node"
    
    return node_data

def get_node_label(node):
    """Get node label/type for grouping"""
    label = get_value(node, "label") or get_value(node, "type")
    return label if label else "Node"

def prepare_edge(edge):
    """Extract edge data according to schema"""
    edge_data = {}
    
    # Extract schema-defined properties
    for prop in EDGE_PROPERTIES:
        value = get_value(edge, prop)
        if value is not None:
            edge_data[prop] = value
    
    # Set default type if missing
    if "type" not in edge_data:
        edge_data["type"] = "RELATED_TO"
    
    return edge_data


# BATCH IMPORT FUNCTIONS


def create_batches(items, size):
    """Split list into batches"""
    return [items[i:i + size] for i in range(0, len(items), size)]

def import_node_batch(db, graph_name, label, batch, batch_num, total):
    """Import one batch of nodes"""
    try:
        g = db.select_graph(graph_name)
        
        # Clean label for Cypher
        safe_label = label.replace(" ", "_").replace("-", "_")
        
        # Create Cypher query with UNWIND
        cypher = f"""
        UNWIND $nodes AS node
        CREATE (n:`{safe_label}`)
        SET n.id = node.id,
            n.name = node.name,
            n.type = node.type,
            n.confidence = node.confidence,
            n.created_at = node.created_at
        """
        
        g.query(cypher, {"nodes": batch})
        
        safe_print(f"   [Thread-{batch_num}] ✅ {len(batch)} nodes ({label})")
        return {"success": True, "count": len(batch)}
        
    except Exception as e:
        safe_print(f"   [Thread-{batch_num}] ❌ Error: {e}")
        return {"success": False, "error": str(e)}

def import_edge_batch(db, graph_name, rel_type, batch, batch_num, total):
    """Import one batch of edges"""
    try:
        g = db.select_graph(graph_name)
        
        # Clean relationship type for Cypher
        safe_rel = rel_type.replace(" ", "_").replace("-", "_").upper()
        
        # Create Cypher query with UNWIND
        cypher = f"""
        UNWIND $edges AS edge
        MATCH (source {{id: edge.source_id}})
        MATCH (target {{id: edge.target_id}})
        CREATE (source)-[r:`{safe_rel}`]->(target)
        SET r.id = edge.id,
            r.type = edge.type,
            r.confidence = edge.confidence,
            r.created_at = edge.created_at
        """
        
        g.query(cypher, {"edges": batch})
        
        safe_print(f"   [Thread-{batch_num}] ✅ {len(batch)} edges ({rel_type})")
        return {"success": True, "count": len(batch)}
        
    except Exception as e:
        safe_print(f"   [Thread-{batch_num}] ❌ Error: {e}")
        return {"success": False, "error": str(e)}


# PARALLEL IMPORT


def import_nodes(db, graph_name, nodes):
    """Import all nodes with multi-threading"""
    if not nodes:
        safe_print("   No nodes to import")
        return 0
    
    safe_print(f"\n🔷 IMPORTING NODES")
    
    # Group nodes by label
    nodes_by_label = {}
    skipped = 0
    
    for node in nodes:
        node_data = prepare_node(node)
        
        # Must have ID
        if not node_data.get("id"):
            skipped += 1
            continue
        
        label = get_node_label(node)
        nodes_by_label.setdefault(label, []).append(node_data)
    
    if skipped > 0:
        safe_print(f"   ⚠️  Skipped {skipped} nodes (no ID)")
    
    total_imported = 0
    
    # Import each label type
    for label, node_list in nodes_by_label.items():
        safe_print(f"\n   📊 {label}: {len(node_list)} nodes")
        
        batches = create_batches(node_list, BATCH_SIZE)
        safe_print(f"   📦 {len(batches)} batches")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(import_node_batch, db, graph_name, label, batch, i, len(batches))
                for i, batch in enumerate(batches, 1)
            ]
            
            for future in as_completed(futures):
                result = future.result()
                if result["success"]:
                    total_imported += result["count"]
    
    safe_print(f"\n   ✅ Imported {total_imported} nodes")
    return total_imported

def import_edges(db, graph_name, edges):
    """Import all edges with multi-threading"""
    if not edges:
        safe_print("   No edges to import")
        return 0
    
    safe_print(f"\n🔶 IMPORTING EDGES")
    
    # Group edges by type
    edges_by_type = {}
    skipped = 0
    
    for edge in edges:
        edge_data = prepare_edge(edge)
        
        # Must have source_id and target_id
        if not edge_data.get("source_id") or not edge_data.get("target_id"):
            skipped += 1
            continue
        
        edge_type = edge_data.get("type", "RELATED_TO")
        edges_by_type.setdefault(edge_type, []).append(edge_data)
    
    if skipped > 0:
        safe_print(f"   ⚠️  Skipped {skipped} edges (no source/target)")
    
    total_imported = 0
    
    # Import each relationship type

    for rel_type, edge_list in edges_by_type.items():
        safe_print(f"\n   📊 {rel_type}: {len(edge_list)} edges")
        
        batches = create_batches(edge_list, BATCH_SIZE)
        safe_print(f"   📦 {len(batches)} batches")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(import_edge_batch, db, graph_name, rel_type, batch, i, len(batches))
                for i, batch in enumerate(batches, 1)
            ]
            
            for future in as_completed(futures):
                result = future.result()
                if result["success"]:
                    total_imported += result["count"]
    
    safe_print(f"\n   ✅ Imported {total_imported} edges")
    return total_imported


# VERIFICATION


def verify_graph(db, graph_name):
    """Verify import results"""
    safe_print(f"\n🔍 VERIFICATION")
    
    try:
        g = db.select_graph(graph_name)
        
        # Count nodes
        result = g.query("MATCH (n) RETURN count(n) as count")
        nodes = result.result_set[0][0] if result.result_set else 0
        
        # Count edges
        result = g.query("MATCH ()-[r]->() RETURN count(r) as count")
        edges = result.result_set[0][0] if result.result_set else 0
        
        safe_print(f"   📍 Nodes: {nodes}")
        safe_print(f"   🔗 Edges: {edges}")
        
        return nodes, edges
        
    except Exception as e:
        safe_print(f"   ❌ Error: {e}")
        return 0, 0


# MAIN


def main():
    """Main import function"""
    
    print("\n" + "="*70)
    print("🚀 FalkorDB Graph Importer")
    print("="*70)
    print(f"\n📄 File: {JSON_FILE}")
    print(f"🔧 Batch: {BATCH_SIZE} | Workers: {MAX_WORKERS}")
    print(f"🌐 FalkorDB: {HOST}:{PORT}")
    print("\n" + "="*70)
    
    # Check file exists
    if not os.path.exists(JSON_FILE):
        print(f"\n❌ File not found: {JSON_FILE}")
        return
    
    # Load JSON
    print(f"\n📂 Loading data...")
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"✅ Found {len(data)} graph(s)")
    
    # Connect to FalkorDB
    print(f"🔌 Connecting to FalkorDB...")
    db = FalkorDB(host=HOST, port=PORT)
    print(f"✅ Connected")
    
    # Process each graph
    for graph_name, graph_data in data.items():
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        
        print("\n" + "="*70)
        print(f"📊 Graph: {graph_name}")
        print(f"   📍 {len(nodes)} nodes")
        print(f"   🔗 {len(edges)} edges")
        print("="*70)
        
        # Import
        import_nodes(db, graph_name, nodes)
        import_edges(db, graph_name, edges)
        
        # Verify
        verify_graph(db, graph_name)
        
        print(f"\n✅ Graph '{graph_name}' completed")
    
    print("\n" + "="*70)
    print("🎉 ALL DONE!")
    print("="*70 + "\n")


# RUN


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Stopped by user")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


