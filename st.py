

# # streamlit_kgraph_dashboard.py
# # Improved Streamlit dashboard to visualize FalkorDB graphs
# # - Sidebar contains connection & graph selector
# # - Top tabs: Overview / Search
# # - Robust PyVis handling (on error it disables PyVis for the session)
# # - Search tab supports searching by name, id, type, and label
# # Usage: streamlit run streamlit_kgraph_dashboard.py

# import streamlit as st
# import pandas as pd
# import plotly.express as px
# import networkx as nx
# import tempfile
# import os
# import json

# # Try to import pyvis; if not available we'll fall back to Plotly network plot
# try:
#     from pyvis.network import Network
#     PYVIS_INSTALLED = True
# except Exception:
#     PYVIS_INSTALLED = False

# # FalkorDB client - make sure falkordb package is installed
# try:
#     from falkordb import FalkorDB
# except Exception:
#     FalkorDB = None

# st.set_page_config(page_title="Knowledge Graph Dashboard", layout="wide")
# st.title("📊 Knowledge Graph Visualization — FalkorDB")

# # -----------------------------
# # Sidebar: connection + graph selector (moved here)
# # -----------------------------
# st.sidebar.header("Connection")
# host = st.sidebar.text_input("FalkorDB host", value="localhost")
# port = st.sidebar.number_input("FalkorDB port", value=6379, step=1)
# connect_button = st.sidebar.button("Connect")

# # Option to load local JSON export
# st.sidebar.markdown("---")
# st.sidebar.header("Local JSON (optional)")
# json_file = st.sidebar.file_uploader("Upload FalkorDB export JSON", type=["json"])

# # Cached connection helper
# @st.cache_resource
# def get_db(host, port):
#     if FalkorDB is None:
#         return None
#     try:
#         return FalkorDB(host=host, port=port)
#     except Exception:
#         return None

# # initialize session flags for pyvis
# if 'pyvis_disabled' not in st.session_state:
#     st.session_state['pyvis_disabled'] = False

# # only try to create client when user clicks Connect or when reading from cache
# db = get_db(host, port) if not connect_button else get_db(host, port)

# if db is None and not json_file:
#     st.sidebar.error("FalkorDB client not available or connection failed. If you want you can upload a JSON export in the sidebar.")

# # -----------------------------
# # Helper functions
# # -----------------------------

# def safe_query(graph, cypher, params=None):
#     try:
#         result = graph.query(cypher, params or {})
#         rows = getattr(result, "result_set", None)
#         return rows if rows is not None else []
#     except Exception as e:
#         # return an empty list rather than raising (UI should stay responsive)
#         st.warning(f"Query error: {e}")
#         return []

# # read json file into local_data if uploaded
# local_data = {}
# if json_file is not None:
#     try:
#         local_data = json.load(json_file)
#     except Exception as e:
#         st.sidebar.error(f"Failed to load JSON: {e}")

# # get graphs list either from DB or local JSON
# graphs = []
# if local_data:
#     graphs = list(local_data.keys())
# elif db is not None:
#     try:
#         graphs = db.list_graphs()
#     except Exception:
#         graphs = []

# if not graphs:
#     graphs = ["-"]

# # Graph selector placed in sidebar (as requested)
# selected_graph = st.sidebar.selectbox("Select graph", options=graphs, index=0 if graphs else 0)

# # Top-level tabs: Overview and Search
# tab_overview, tab_search = st.tabs(["Overview", "Search / Find"])

# # Utility: load nodes/edges for the selected graph (up to limits)
# @st.cache_data(ttl=300)
# def load_graph_data(graph_name):
#     nodes_df = pd.DataFrame()
#     edges_df = pd.DataFrame()

#     if graph_name == "-":
#         return nodes_df, edges_df

#     if local_data:
#         g = local_data.get(graph_name, {})
#         nodes = g.get("nodes", [])
#         edges = g.get("edges", [])
#         nodes_df = pd.DataFrame([{
#             "id": n.get("id"),
#             "name": n.get("name") or n.get("properties", {}).get("name"),
#             "type": n.get("type") or n.get("properties", {}).get("type"),
#             "label": n.get("label") or (n.get("properties", {}).get("label"))
#         } for n in nodes])
#         edges_df = pd.DataFrame([{
#             "id": e.get("id"),
#             "type": e.get("type"),
#             "source": e.get("source_id"),
#             "target": e.get("target_id"),
#             "confidence": e.get("confidence")
#         } for e in edges])
#         return nodes_df, edges_df

#     # otherwise fetch from DB
#     try:
#         g = db.select_graph(graph_name)
#     except Exception as e:
#         st.warning(f"Could not select graph: {e}")
#         return nodes_df, edges_df

#     # fetch nodes and edges (limits for performance)
#     node_fetch = safe_query(g, "MATCH (n) RETURN n.id as id, n.name as name, n.type as type, n.label as label LIMIT 1000")
#     edge_fetch = safe_query(g, "MATCH (a)-[r]->(b) RETURN r.id as id, r.type as type, a.id as source, b.id as target, r.confidence as confidence LIMIT 2000")

#     if node_fetch:
#         nodes_df = pd.DataFrame(node_fetch, columns=["id", "name", "type", "label"])    
#     if edge_fetch:
#         edges_df = pd.DataFrame(edge_fetch, columns=["id", "type", "source", "target", "confidence"])    

#     return nodes_df, edges_df

# # Helper to get neighbors for a node id
# @st.cache_data(ttl=120)
# def get_neighbors(graph_name, node_id):
#     neighbors = []
#     relations = []
#     if local_data:
#         g = local_data.get(graph_name, {})
#         nodes = g.get("nodes", [])
#         edges = g.get("edges", [])
#         # find edges where node is source or target
#         for e in edges:
#             if e.get("source_id") == node_id or e.get("target_id") == node_id:
#                 relations.append(e)
#                 # add neighbor id
#                 nid = e.get("source_id") if e.get("target_id") == node_id else e.get("target_id")
#                 # find node
#                 neighbor = next((n for n in nodes if n.get("id") == nid), None)
#                 if neighbor:
#                     neighbors.append(neighbor)
#         return neighbors, relations

#     # DB path
#     try:
#         g = db.select_graph(graph_name)
#     except Exception:
#         return neighbors, relations

#     # Return immediate (1-hop) neighbors
#     q = "MATCH (n {id: $nid})-[r]-(m) RETURN r.id as rid, type(r) as rtype, r.confidence as confidence, m.id as mid, m.name as mname, m.type as mtype LIMIT 500"
#     rows = safe_query(g, q, {"nid": node_id})
#     for row in rows:
#         relations.append({"rid": row[0], "rtype": row[1], "confidence": row[2], "mid": row[3]})
#         neighbors.append({"id": row[3], "name": row[4], "type": row[5]})
#     return neighbors, relations

# # -----------------------------
# # Overview tab
# # -----------------------------
# with tab_overview:
#     st.header(f"Graph Overview — {selected_graph}")
#     nodes_df, edges_df = load_graph_data(selected_graph)

#     # Summary cards
#     c1, c2, c3 = st.columns(3)
#     c1.metric("Nodes", value=len(nodes_df))
#     c2.metric("Edges", value=len(edges_df))
#     # entity distribution small table
#     with c3:
#         st.write("Top entity types")
#         if not nodes_df.empty and "type" in nodes_df.columns:
#             st.dataframe(nodes_df['type'].value_counts().rename_axis('type').reset_index(name='count').head(10))
#         else:
#             st.write("N/A")

#     st.subheader("Entity type breakdown")
#     if not nodes_df.empty and 'type' in nodes_df.columns:
#         agg = nodes_df.groupby('type').size().reset_index(name='count')
#         fig = px.bar(agg, x='type', y='count', title='Entities by type')
#         st.plotly_chart(fig, use_container_width=True)
#     else:
#         st.info("No node type information available")

#     st.subheader("Relationship type breakdown")
#     if not edges_df.empty and 'type' in edges_df.columns:
#         rd = edges_df.groupby('type').size().reset_index(name='count')
#         fig2 = px.pie(rd, names='type', values='count', title='Relationships')
#         st.plotly_chart(fig2, use_container_width=True)
#     else:
#         st.info("No relationship information available")

#     # Graph visualization area
#     st.subheader("Interactive graph (top 50 nodes)")
#     if not edges_df.empty and not nodes_df.empty:
#         G = nx.DiGraph()
#         for _, row in nodes_df.iterrows():
#             nid = str(row.get('id'))
#             G.add_node(nid, label=str(row.get('name') or nid), ntype=str(row.get('type') or 'Node'))
#         for _, row in edges_df.iterrows():
#             src = str(row.get('source'))
#             tgt = str(row.get('target'))
#             if src and tgt:
#                 G.add_edge(src, tgt, rtype=row.get('type') or 'RELATED_TO')

#         if G.number_of_nodes() > 50:
#             degrees = dict(G.degree())
#             top_nodes = sorted(degrees, key=lambda x: degrees[x], reverse=True)[:50]
#             H = G.subgraph(top_nodes).copy()
#         else:
#             H = G

#         # Try pyvis only if installed and not disabled in session
#         if PYVIS_INSTALLED and not st.session_state.get('pyvis_disabled', False):
#             try:
#                 net = Network(height='600px', width='100%', directed=True)
#                 color_map = {}
#                 palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2"]
#                 for i, n in enumerate(H.nodes(data=True)):
#                     ntype = n[1].get('ntype', 'Node')
#                     if ntype not in color_map:
#                         color_map[ntype] = palette[len(color_map) % len(palette)]
#                     net.add_node(n[0], label=n[1].get('label', n[0]), title=f"Type: {ntype}", color=color_map[ntype])
#                 for u, v, data in H.edges(data=True):
#                     net.add_edge(u, v, title=str(data.get('rtype', 'RELATED_TO')))

#                 tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.html')
#                 tmp_name = tmp.name
#                 tmp.close()
#                 net.show(tmp_name)
#                 with open(tmp_name, 'r', encoding='utf-8') as f:
#                     html = f.read()
#                 st.components.v1.html(html, height=650, scrolling=True)
#             except Exception as e:
#                 # Disable further pyvis attempts for this session to avoid noise
#                 st.session_state['pyvis_disabled'] = True
#                 st.warning(f"PyVis rendering failed — falling back to Plotly visualization. ({e})")
#                 # clean temp if exists
#                 try:
#                     if tmp_name and os.path.exists(tmp_name):
#                         os.unlink(tmp_name)
#                 except Exception:
#                     pass
#                 # fallback to plotly renderer below

#         # If pyvis is not available or disabled, use Plotly fallback
#         if not PYVIS_INSTALLED or st.session_state.get('pyvis_disabled', False):
#             pos = nx.spring_layout(H, seed=42)
#             edge_x = []
#             edge_y = []
#             for edge in H.edges():
#                 x0, y0 = pos[edge[0]]
#                 x1, y1 = pos[edge[1]]
#                 edge_x += [x0, x1, None]
#                 edge_y += [y0, y1, None]

#             node_x = []
#             node_y = []
#             labels = []
#             for n, data in H.nodes(data=True):
#                 x, y = pos[n]
#                 node_x.append(x)
#                 node_y.append(y)
#                 labels.append(data.get('label', n))

#             import plotly.graph_objects as go
#             edge_trace = go.Scatter(x=edge_x, y=edge_y, mode='lines', hoverinfo='none')
#             node_trace = go.Scatter(x=node_x, y=node_y, mode='markers+text', text=labels, hoverinfo='text')
#             fig = go.Figure(data=[edge_trace, node_trace])
#             fig.update_layout(title='Graph (fallback)', showlegend=False)
#             st.plotly_chart(fig, use_container_width=True)

#     else:
#         st.info("Not enough data to render a graph visualization.")

# # -----------------------------
# # Search tab
# # -----------------------------
# with tab_search:
#     st.header("Find / Query")

#     st.markdown("Search nodes by different fields: `name`, `id`, `type`, `label`. For DB-backed graphs the search is case-insensitive and uses substring matching where appropriate.")

#     if selected_graph == "-":
#         st.info("Select a graph in the sidebar first.")
#     else:
#         search_by = st.selectbox("Search by", options=["name", "id", "type", "label", "all"], index=0)
#         q = st.text_input("Search query")
#         limit = st.number_input("Limit", min_value=1, max_value=1000, value=50)

#         if st.button("Find"):
#             results = []
#             # Local JSON search
#             if local_data:
#                 nodes = local_data.get(selected_graph, {}).get('nodes', [])
#                 if search_by == 'name':
#                     results = [n for n in nodes if q.lower() in (n.get('name','') or '').lower()][:limit]
#                 elif search_by == 'id':
#                     results = [n for n in nodes if n.get('id') == q][:limit]
#                 elif search_by == 'type':
#                     results = [n for n in nodes if q.lower() in ((n.get('type') or '')).lower()][:limit]
#                 elif search_by == 'label':
#                     results = [n for n in nodes if q.lower() in ((n.get('label') or n.get('properties', {}).get('label','')) or '').lower()][:limit]
#                 else:
#                     # all: search across id, name, type, label
#                     def match_all(n):
#                         for k in ['id','name','type','label']:
#                             if k == 'id' and n.get('id') == q:
#                                 return True
#                             if isinstance(n.get(k), str) and q.lower() in n.get(k,'').lower():
#                                 return True
#                         return False
#                     results = [n for n in nodes if match_all(n)][:limit]

#                 if results:
#                     df = pd.DataFrame([{"id": r.get('id'), "name": r.get('name'), "type": r.get('type'), "label": r.get('label')} for r in results])
#                     st.dataframe(df)

#                     # allow expand of first result
#                     if st.button("Show neighbors of first result"):
#                         nid = results[0].get('id')
#                         neighbors, relations = get_neighbors(selected_graph, nid)
#                         st.write("Neighbors:")
#                         st.dataframe(pd.DataFrame(neighbors))
#                         st.write("Relations:")
#                         st.dataframe(pd.DataFrame(relations))
#                 else:
#                     st.info("No results found in local JSON")

#             else:
#                 # DB search
#                 try:
#                     g = db.select_graph(selected_graph)
#                 except Exception as e:
#                     st.error(f"Could not select graph: {e}")
#                     g = None

#                 if g is not None:
#                     if search_by == 'name':
#                         qsql = "MATCH (n) WHERE toLower(n.name) CONTAINS $q RETURN n.id, n.name, n.type, labels(n) LIMIT $limit"
#                         rows = safe_query(g, qsql, {"q": q.lower(), "limit": int(limit)})
#                         results = [{'id': r[0], 'name': r[1], 'type': r[2], 'labels': r[3]} for r in rows]

#                     elif search_by == 'id':
#                         qsql = "MATCH (n {id: $q}) RETURN n.id, n.name, n.type, labels(n) LIMIT $limit"
#                         rows = safe_query(g, qsql, {"q": q, "limit": int(limit)})
#                         results = [{'id': r[0], 'name': r[1], 'type': r[2], 'labels': r[3]} for r in rows]

#                     elif search_by == 'type':
#                         qsql = "MATCH (n) WHERE toLower(n.type) CONTAINS $q RETURN n.id, n.name, n.type, labels(n) LIMIT $limit"
#                         rows = safe_query(g, qsql, {"q": q.lower(), "limit": int(limit)})
#                         results = [{'id': r[0], 'name': r[1], 'type': r[2], 'labels': r[3]} for r in rows]

#                     elif search_by == 'label':
#                         # labels(n) returns a list of labels; use ANY ... IN labels(n)
#                         qsql = "MATCH (n) WHERE ANY(l IN labels(n) WHERE toLower(l) CONTAINS $q) RETURN n.id, n.name, n.type, labels(n) LIMIT $limit"
#                         rows = safe_query(g, qsql, {"q": q.lower(), "limit": int(limit)})
#                         results = [{'id': r[0], 'name': r[1], 'type': r[2], 'labels': r[3]} for r in rows]

#                     else:
#                         # all fields
#                         qsql = "MATCH (n) WHERE toLower(n.name) CONTAINS $q OR toLower(n.type) CONTAINS $q OR n.id = $q RETURN n.id, n.name, n.type, labels(n) LIMIT $limit"
#                         rows = safe_query(g, qsql, {"q": q.lower(), "limit": int(limit)})
#                         results = [{'id': r[0], 'name': r[1], 'type': r[2], 'labels': r[3]} for r in rows]

#                     if results:
#                         st.dataframe(pd.DataFrame(results))
#                         # Expand neighbors for first result
#                         if st.button("Show neighbors of first result"):
#                             nid = results[0]['id']
#                             neighbors, relations = get_neighbors(selected_graph, nid)
#                             st.write("Neighbors:")
#                             st.dataframe(pd.DataFrame(neighbors))
#                             st.write("Relations:")
#                             st.dataframe(pd.DataFrame(relations))
#                     else:
#                         st.info("No results found")

# # Footer
# st.markdown("---")
# st.caption("Improved dashboard — uses sidebar graph selector and search tab. PyVis will be auto-disabled if rendering fails during this session.")


# ==================================imoroveved st.py==================================










# # streamlit_kgraph_dashboard_complete.py
# # Complete Knowledge Graph Dashboard - Meeting All Client Requirements
# # Phases: Core Features, Advanced Features, Analytics & Polish

# import os
# import json
# import tempfile
# import re
# import base64
# from io import BytesIO
# from typing import Tuple, List, Dict, Any, Optional, Set
# from datetime import datetime
# from collections import defaultdict, Counter

# import streamlit as st
# import pandas as pd
# import plotly.express as px
# import plotly.graph_objects as go
# import networkx as nx

# # PyVis for interactive graphs
# try:
#     from pyvis.network import Network
#     PYVIS_INSTALLED = True
# except Exception:
#     PYVIS_INSTALLED = False

# # FalkorDB client
# try:
#     from falkordb import FalkorDB
# except Exception:
#     FalkorDB = None

# # Page config
# st.set_page_config(
#     page_title="🧠 Knowledge Graph Dashboard",
#     page_icon="🧠",
#     layout="wide",
#     initial_sidebar_state="expanded"
# )

# # Custom CSS
# st.markdown("""
# <style>
#     /* Main gradient background */
#     .stApp {
#         background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
#     }
    
#     /* Sidebar - Clean white design */
#     [data-testid="stSidebar"] {
#         background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
#     }
    
#     [data-testid="stSidebar"] .stMarkdown {
#         color: #1f2937 !important;
#     }
    
#     [data-testid="stSidebar"] label {
#         color: #1f2937 !important;
#         font-weight: 600 !important;
#     }
    
#     [data-testid="stSidebar"] input,
#     [data-testid="stSidebar"] select,
#     [data-testid="stSidebar"] .stSelectbox {
#         background: white !important;
#         color: #1f2937 !important;
#         border: 1px solid #d1d5db !important;
#         border-radius: 8px !important;
#     }
    
#     [data-testid="stSidebar"] .stSelectbox > div {
#         background: white !important;
#         color: #1f2937 !important;
#     }
    
#     [data-testid="stSidebar"] .stNumberInput input,
#     [data-testid="stSidebar"] .stTextInput input {
#         background: white !important;
#         color: #1f2937 !important;
#     }
    
#     [data-testid="stSidebar"] .stFileUploader {
#         background: white !important;
#         border: 2px dashed #667eea !important;
#         border-radius: 8px !important;
#         padding: 10px !important;
#     }
    
#     [data-testid="stSidebar"] hr {
#         border-color: #d1d5db !important;
#     }
    
#     /* Card styling */
#     .metric-card {
#         background: rgba(255, 255, 255, 0.95);
#         padding: 20px;
#         border-radius: 15px;
#         box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
#         backdrop-filter: blur(10px);
#         border: 1px solid rgba(255, 255, 255, 0.2);
#     }
    
#     .main-header {
#         background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
#         padding: 30px;
#         border-radius: 20px;
#         color: white;
#         text-align: center;
#         margin-bottom: 30px;
#         box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
#     }
    
#     .stButton button {
#         background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
#         color: white;
#         border-radius: 25px;
#         padding: 10px 30px;
#         border: none;
#         font-weight: 600;
#         transition: all 0.3s ease;
#     }
    
#     .stButton button:hover {
#         transform: translateY(-2px);
#         box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
#     }
    
#     .node-card {
#         background: white;
#         padding: 20px;
#         border-radius: 15px;
#         margin: 10px 0;
#         box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
#         border-left: 4px solid #667eea;
#     }
    
#     .property-badge {
#         display: inline-block;
#         background: #e0e7ff;
#         padding: 4px 12px;
#         border-radius: 12px;
#         margin: 3px;
#         font-size: 13px;
#         color: #4338ca;
#     }
# </style>
# """, unsafe_allow_html=True)

# # Header
# st.markdown("""
# <div class="main-header">
#     <h1>🧠 Knowledge Graph Dashboard</h1>
#     <p style="font-size: 18px; margin-top: 10px;">Comprehensive Graph Analysis & Visualization Platform</p>
# </div>
# """, unsafe_allow_html=True)

# # Initialize session state
# if "pyvis_disabled" not in st.session_state:
#     st.session_state["pyvis_disabled"] = False
# if "selected_node" not in st.session_state:
#     st.session_state["selected_node"] = None
# if "subgraph_center" not in st.session_state:
#     st.session_state["subgraph_center"] = None

# # ==================== SIDEBAR ====================
# with st.sidebar:
#     st.markdown("### 🔌 Connection Settings")
#     host = st.text_input("Host", value="localhost", help="FalkorDB host address")
#     port = st.number_input("Port", value=6379, step=1, help="FalkorDB port number")
    
#     connect_btn = st.button("🔗 Connect to FalkorDB", use_container_width=True)
    
#     st.markdown("---")
#     st.markdown("### 📁 Local Data (Optional)")
#     json_file = st.file_uploader("Upload JSON Export", type=["json"], 
#                                  help="Upload your knowledge graph JSON file")
    
#     st.markdown("---")
#     st.markdown("### ℹ️ About")
#     st.caption("**Version:** 1.0.0")
#     st.caption("**Features:**")
#     st.caption("✓ Interactive Graph Visualization")
#     st.caption("✓ Node Search & Exploration")
#     st.caption("✓ Advanced Analytics")
#     st.caption("✓ Multi-Graph Comparison")
#     st.caption("✓ Export & Download")

# # ==================== DATABASE CONNECTION ====================
# @st.cache_resource
# def get_db(host: str, port: int):
#     if FalkorDB is None:
#         return None
#     try:
#         return FalkorDB(host=host, port=port)
#     except Exception:
#         return None

# db = get_db(host, port) if connect_btn else None

# # Load local JSON
# local_data: Dict[str, Any] = {}
# if json_file is not None:
#     try:
#         local_data = json.load(json_file)
#         st.sidebar.success("✅ JSON loaded successfully!")
#     except Exception as e:
#         st.sidebar.error(f"❌ Failed to load JSON: {e}")

# # Get available graphs
# graphs: List[str] = []
# if local_data:
#     graphs = list(local_data.keys())
# elif db is not None:
#     try:
#         graphs = db.list_graphs()
#         if graphs:
#             st.sidebar.success(f"✅ Connected! Found {len(graphs)} graphs")
#     except Exception as e:
#         st.sidebar.error(f"❌ Connection failed: {e}")
#         graphs = []

# if not graphs:
#     graphs = ["-"]

# # ==================== HELPER FUNCTIONS ====================

# def get_all_properties(item: Dict) -> Dict[str, Any]:
#     """Extract all properties from a node/edge"""
#     all_props = {}
#     for key, value in item.items():
#         if key != 'properties':
#             all_props[key] = value
#     if 'properties' in item:
#         all_props.update(item['properties'])
#     return all_props

# def safe_query(graph, cypher: str, params: Dict = None):
#     """Execute Cypher query safely"""
#     try:
#         result = graph.query(cypher, params or {})
#         rows = getattr(result, "result_set", None)
#         return rows if rows is not None else []
#     except Exception as e:
#         st.warning(f"Query error: {e}")
#         return []

# @st.cache_data(ttl=300)
# def load_graph_data(graph_name: str):
#     """Load graph data from JSON or DB"""
#     nodes_list = []
#     edges_list = []
    
#     if local_data:
#         g = local_data.get(graph_name, {})
#         nodes_list = g.get("nodes", [])
#         edges_list = g.get("edges", [])
#     elif db is not None and graph_name != "-":
#         try:
#             g = db.select_graph(graph_name)
#             # Fetch nodes
#             node_rows = safe_query(g, "MATCH (n) RETURN n.id, n.name, n.type, n.label, properties(n) LIMIT 1000")
#             for row in node_rows:
#                 nodes_list.append({
#                     'id': row[0],
#                     'name': row[1],
#                     'type': row[2],
#                     'label': row[3],
#                     'properties': row[4] if len(row) > 4 else {}
#                 })
#             # Fetch edges
#             edge_rows = safe_query(g, "MATCH (a)-[r]->(b) RETURN r.id, type(r), a.id, b.id, r.confidence, properties(r) LIMIT 2000")
#             for row in edge_rows:
#                 edges_list.append({
#                     'id': row[0],
#                     'type': row[1],
#                     'source_id': row[2],
#                     'target_id': row[3],
#                     'confidence': row[4] if len(row) > 4 else None,
#                     'properties': row[5] if len(row) > 5 else {}
#                 })
#         except Exception as e:
#             st.error(f"Error loading graph: {e}")
    
#     return nodes_list, edges_list

# def get_graph_statistics(nodes: List[Dict], edges: List[Dict]) -> Dict:
#     """Calculate graph statistics"""
#     stats = {
#         'total_nodes': len(nodes),
#         'total_edges': len(edges),
#         'node_types': Counter(),
#         'edge_types': Counter(),
#         'avg_connections': 0,
#         'isolated_nodes': 0
#     }
    
#     # Count types
#     for node in nodes:
#         props = get_all_properties(node)
#         ntype = props.get('type', 'Unknown')
#         stats['node_types'][ntype] += 1
    
#     for edge in edges:
#         props = get_all_properties(edge)
#         etype = props.get('type', 'Unknown')
#         stats['edge_types'][etype] += 1
    
#     # Calculate connectivity
#     if nodes:
#         stats['avg_connections'] = len(edges) / len(nodes)
    
#     # Find isolated nodes - with validation
#     connected_nodes = set()
#     for edge in edges:
#         src = edge.get('source_id')
#         tgt = edge.get('target_id')
#         # Only add if not None
#         if src is not None:
#             connected_nodes.add(src)
#         if tgt is not None:
#             connected_nodes.add(tgt)
    
#     stats['isolated_nodes'] = len(nodes) - len(connected_nodes)
    
#     return stats

# def fuzzy_search_nodes(nodes: List[Dict], query: str) -> List[Dict]:
#     """Fuzzy search for nodes"""
#     query_lower = query.lower()
#     results = []
    
#     for node in nodes:
#         props = get_all_properties(node)
#         # Search in name, id, type
#         searchable = f"{props.get('name', '')} {props.get('id', '')} {props.get('type', '')}".lower()
#         if query_lower in searchable:
#             results.append(node)
    
#     return results

# def get_node_neighbors(node_id: str, nodes: List[Dict], edges: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
#     """Get all neighbors and relationships for a node"""
#     neighbors = []
#     relationships = []
    
#     for edge in edges:
#         src = edge.get('source_id')
#         tgt = edge.get('target_id')
        
#         # Skip edges with None values
#         if src is None or tgt is None:
#             continue
            
#         if src == node_id or tgt == node_id:
#             relationships.append(edge)
#             # Get neighbor
#             neighbor_id = tgt if src == node_id else src
#             neighbor = next((n for n in nodes if n.get('id') == neighbor_id), None)
#             if neighbor:
#                 neighbors.append(neighbor)
    
#     return neighbors, relationships

# def get_subgraph(center_node_id: str, nodes: List[Dict], edges: List[Dict], max_depth: int = 1) -> Tuple[List[Dict], List[Dict]]:
#     """Get subgraph within N hops from center node"""
#     subgraph_nodes = set([center_node_id])
#     subgraph_edges = []
    
#     current_level = set([center_node_id])
    
#     for depth in range(max_depth):
#         next_level = set()
#         for node_id in current_level:
#             for edge in edges:
#                 src = edge.get('source_id')
#                 tgt = edge.get('target_id')
                
#                 # Skip edges with None values
#                 if src is None or tgt is None:
#                     continue
                
#                 if src == node_id:
#                     next_level.add(tgt)
#                     if edge not in subgraph_edges:
#                         subgraph_edges.append(edge)
#                 elif tgt == node_id:
#                     next_level.add(src)
#                     if edge not in subgraph_edges:
#                         subgraph_edges.append(edge)
        
#         subgraph_nodes.update(next_level)
#         current_level = next_level
    
#     subgraph_nodes_list = [n for n in nodes if n.get('id') in subgraph_nodes]
    
#     return subgraph_nodes_list, subgraph_edges

# def create_network_graph(nodes: List[Dict], edges: List[Dict], height: str = "700px", show_labels: bool = True):
#     """Create interactive network visualization"""
#     if not nodes:
#         st.info("No nodes to visualize")
#         return
    
#     G = nx.DiGraph()
    
#     # Add nodes
#     for node in nodes:
#         props = get_all_properties(node)
#         nid = props.get('id')
#         if nid is None:
#             continue  # Skip nodes without ID
#         name = props.get('name', nid)
#         ntype = props.get('type', 'Node')
#         G.add_node(nid, label=name, ntype=ntype, props=props)
    
#     # Add edges - with validation
#     for edge in edges:
#         props = get_all_properties(edge)
#         src = props.get('source_id')
#         tgt = props.get('target_id')
        
#         # Skip if source or target is None or not in nodes
#         if src is None or tgt is None:
#             continue
#         if src not in G.nodes or tgt not in G.nodes:
#             continue
            
#         G.add_edge(src, tgt, etype=props.get('type', 'RELATED'), props=props)
    
#     # Try PyVis first
#     if PYVIS_INSTALLED and not st.session_state.get('pyvis_disabled'):
#         try:
#             net = Network(height=height, width="100%", directed=True, 
#                          bgcolor="#f8f9fa", font_color="#333")
            
#             # Color palette for different types
#             colors = ['#667eea', '#764ba2', '#f093fb', '#4facfe', 
#                      '#43e97b', '#fa709a', '#fee140', '#30cfd0']
            
#             type_colors = {}
#             for node, data in G.nodes(data=True):
#                 ntype = data.get('ntype', 'Node')
#                 if ntype not in type_colors:
#                     type_colors[ntype] = colors[len(type_colors) % len(colors)]
                
#                 props = data.get('props', {})
#                 title = f"<b>{data.get('label', node)}</b><br>Type: {ntype}<br>ID: {node}"
                
#                 net.add_node(
#                     node,
#                     label=data.get('label', node) if show_labels else '',
#                     title=title,
#                     color=type_colors[ntype],
#                     size=25
#                 )
            
#             for u, v, data in G.edges(data=True):
#                 etype = data.get('etype', 'RELATED')
#                 net.add_edge(u, v, title=etype, color='#cccccc', width=2)
            
#             net.set_options("""
#             {
#                 "physics": {
#                     "forceAtlas2Based": {
#                         "gravitationalConstant": -50,
#                         "centralGravity": 0.01,
#                         "springLength": 200,
#                         "springConstant": 0.08
#                     },
#                     "maxVelocity": 50,
#                     "solver": "forceAtlas2Based",
#                     "timestep": 0.35,
#                     "stabilization": {"iterations": 150}
#                 }
#             }
#             """)
            
#             tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
#             net.save_graph(tmp.name)
            
#             with open(tmp.name, 'r', encoding='utf-8') as f:
#                 html = f.read()
            
#             st.components.v1.html(html, height=int(height.replace('px', '')), scrolling=True)
#             os.unlink(tmp.name)
#             return
            
#         except Exception as e:
#             st.session_state['pyvis_disabled'] = True
#             st.warning(f"PyVis failed, using fallback: {e}")
    
#     # Fallback to Plotly
#     pos = nx.spring_layout(G, seed=42, k=2)
    
#     edge_x, edge_y = [], []
#     for edge in G.edges():
#         x0, y0 = pos[edge[0]]
#         x1, y1 = pos[edge[1]]
#         edge_x += [x0, x1, None]
#         edge_y += [y0, y1, None]
    
#     node_x, node_y, labels = [], [], []
#     for n, data in G.nodes(data=True):
#         x, y = pos[n]
#         node_x.append(x)
#         node_y.append(y)
#         labels.append(data.get('label', n))
    
#     edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines", 
#                            line=dict(width=1, color="#ccc"), hoverinfo="none")
#     node_trace = go.Scatter(x=node_x, y=node_y, mode="markers+text", 
#                            text=labels if show_labels else None,
#                            textposition="top center",
#                            marker=dict(size=15, color='#667eea'),
#                            hoverinfo="text", hovertext=labels)
    
#     fig = go.Figure(data=[edge_trace, node_trace])
#     fig.update_layout(
#         showlegend=False,
#         height=int(height.replace('px', '')),
#         xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
#         yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
#         plot_bgcolor='#f8f9fa'
#     )
#     st.plotly_chart(fig, use_container_width=True)

# # ==================== MAIN CONTENT ====================

# # Graph selector in main area (not sidebar as per requirements)
# st.markdown("### 📊 Select Knowledge Graph")
# selected_graph = st.selectbox(
#     "Choose a graph to explore:",
#     options=graphs,
#     index=0,
#     help="Select from available knowledge graphs"
# )

# if selected_graph == "-":
#     st.info("👈 Please upload a JSON file or connect to FalkorDB to get started")
#     st.stop()

# # Load graph data
# nodes_list, edges_list = load_graph_data(selected_graph)

# if not nodes_list:
#     st.warning("No data found in selected graph")
#     st.stop()

# # Calculate statistics
# stats = get_graph_statistics(nodes_list, edges_list)

# # ==================== TABS ====================
# tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
#     "📈 Overview",
#     "🔍 Node Search",
#     "🌐 Graph Visualization", 
#     "🔗 Relationship Explorer",
#     "🎯 Subgraph Viewer",
#     "📊 Analytics & Export"
# ])

# # ==================== TAB 1: OVERVIEW ====================
# with tab1:
#     st.markdown(f"## Graph Overview: {selected_graph}")
    
#     # Statistics cards
#     col1, col2, col3, col4 = st.columns(4)
#     col1.metric("🔵 Total Nodes", stats['total_nodes'])
#     col2.metric("🔗 Total Edges", stats['total_edges'])
#     col3.metric("📊 Avg Connections", f"{stats['avg_connections']:.2f}")
#     col4.metric("⚪ Isolated Nodes", stats['isolated_nodes'])
    
#     st.markdown("---")
    
#     # Charts
#     col1, col2 = st.columns(2)
    
#     with col1:
#         st.markdown("#### Entity Type Distribution")
#         if stats['node_types']:
#             df_types = pd.DataFrame(
#                 [(t, c) for t, c in stats['node_types'].items()],
#                 columns=['Type', 'Count']
#             ).sort_values('Count', ascending=False)
            
#             fig = px.bar(df_types, x='Type', y='Count',
#                         color='Count', color_continuous_scale='Viridis',
#                         title='Nodes by Entity Type')
#             fig.update_layout(xaxis_tickangle=-45)
#             st.plotly_chart(fig, use_container_width=True)
#         else:
#             st.info("No entity type data available")
    
#     with col2:
#         st.markdown("#### Relationship Type Distribution")
#         if stats['edge_types']:
#             df_edges = pd.DataFrame(
#                 [(t, c) for t, c in stats['edge_types'].items()],
#                 columns=['Relationship', 'Count']
#             ).sort_values('Count', ascending=False)
            
#             fig2 = px.pie(df_edges, values='Count', names='Relationship',
#                          title='Relationships by Type',
#                          color_discrete_sequence=px.colors.sequential.RdBu)
#             st.plotly_chart(fig2, use_container_width=True)
#         else:
#             st.info("No relationship data available")

# # ==================== TAB 2: NODE SEARCH ====================
# with tab2:
#     st.markdown("## 🔍 Node Search & Exploration")
    
#     search_query = st.text_input(
#         "Search nodes by name, ID, or type:",
#         placeholder="e.g., blood_pressure, user, fitbit...",
#         help="Fuzzy search across node properties"
#     )
    
#     if search_query:
#         results = fuzzy_search_nodes(nodes_list, search_query)
        
#         if results:
#             st.success(f"Found {len(results)} matching nodes")
            
#             for idx, node in enumerate(results[:20]):  # Limit to 20 results
#                 props = get_all_properties(node)
#                 node_id = props.get('id')
#                 node_name = props.get('name', node_id)
#                 node_type = props.get('type', 'Unknown')
                
#                 with st.expander(f"📌 {node_name} ({node_type})"):
#                     col1, col2 = st.columns([2, 1])
                    
#                     with col1:
#                         st.markdown("**Properties:**")
#                         for key, value in props.items():
#                             if key not in ['id', 'properties'] and value:
#                                 st.write(f"• **{key}:** {value}")
                    
#                     with col2:
#                         if st.button(f"View Neighbors", key=f"view_{idx}"):
#                             st.session_state['selected_node'] = node_id
                    
#                     # Show neighbors if selected
#                     if st.session_state.get('selected_node') == node_id:
#                         neighbors, relationships = get_node_neighbors(node_id, nodes_list, edges_list)
                        
#                         st.markdown(f"**🔗 Connected Nodes ({len(neighbors)}):**")
#                         for neighbor in neighbors[:10]:
#                             n_props = get_all_properties(neighbor)
#                             st.write(f"→ {n_props.get('name', n_props.get('id'))} ({n_props.get('type', 'N/A')})")
                        
#                         st.markdown(f"**🔀 Relationships ({len(relationships)}):**")
#                         for rel in relationships[:10]:
#                             r_props = get_all_properties(rel)
#                             st.write(f"• {r_props.get('type', 'RELATED')} (confidence: {r_props.get('confidence', 'N/A')})")
                        
#                         if st.button(f"Expand to Subgraph", key=f"expand_{idx}"):
#                             st.session_state['subgraph_center'] = node_id
#                             st.info("Go to 'Subgraph Viewer' tab to see the expanded view")
#         else:
#             st.warning("No nodes found matching your search")

# # ==================== TAB 3: GRAPH VISUALIZATION ====================
# with tab3:
#     st.markdown("## 🌐 Interactive Graph Visualization")
    
#     col1, col2 = st.columns([3, 1])
#     with col1:
#         viz_limit = st.slider("Number of nodes to display:", 10, 200, 50, 10)
#     with col2:
#         show_labels = st.checkbox("Show node labels", value=True)
    
#     st.info(f"Displaying top {viz_limit} most connected nodes for performance")
    
#     # Get top connected nodes
#     if nodes_list and edges_list:
#         G_temp = nx.DiGraph()
        
#         # Add all nodes
#         for node in nodes_list:
#             node_id = node.get('id')
#             if node_id is not None:
#                 G_temp.add_node(node_id)
        
#         # Add edges with validation
#         for edge in edges_list:
#             src = edge.get('source_id')
#             tgt = edge.get('target_id')
#             # Only add edge if both nodes exist and are not None
#             if src is not None and tgt is not None and src in G_temp.nodes and tgt in G_temp.nodes:
#                 G_temp.add_edge(src, tgt)
        
#         degrees = dict(G_temp.degree())
#         top_nodes = sorted(degrees, key=lambda x: degrees[x], reverse=True)[:viz_limit]
        
#         viz_nodes = [n for n in nodes_list if n.get('id') in top_nodes]
#         viz_edges = [e for e in edges_list if e.get('source_id') in top_nodes and e.get('target_id') in top_nodes]
        
#         create_network_graph(viz_nodes, viz_edges, height="700px", show_labels=show_labels)

# # ==================== TAB 4: RELATIONSHIP EXPLORER ====================
# with tab4:
#     st.markdown("## 🔗 Relationship Explorer")
    
#     # Get all relationship types
#     rel_types = list(stats['edge_types'].keys())
    
#     if rel_types:
#         selected_rel = st.selectbox("Select relationship type:", rel_types)
        
#         # Filter edges by type
#         filtered_edges = [e for e in edges_list if get_all_properties(e).get('type') == selected_rel]
        
#         st.metric("Relationships found:", len(filtered_edges))
        
#         if filtered_edges:
#             # Create table
#             table_data = []
#             for edge in filtered_edges[:100]:  # Limit to 100
#                 props = get_all_properties(edge)
#                 src_node = next((n for n in nodes_list if n.get('id') == props.get('source_id')), None)
#                 tgt_node = next((n for n in nodes_list if n.get('id') == props.get('target_id')), None)
                
#                 if src_node and tgt_node:
#                     src_props = get_all_properties(src_node)
#                     tgt_props = get_all_properties(tgt_node)
                    
#                     table_data.append({
#                         'Source': src_props.get('name', src_props.get('id')),
#                         'Source Type': src_props.get('type', 'N/A'),
#                         'Relationship': selected_rel,
#                         'Target': tgt_props.get('name', tgt_props.get('id')),
#                         'Target Type': tgt_props.get('type', 'N/A'),
#                         'Confidence': props.get('confidence', 'N/A')
#                     })
            
#             df_rel = pd.DataFrame(table_data)
#             st.dataframe(df_rel, use_container_width=True)
#     else:
#         st.info("No relationship types found")

# # ==================== TAB 5: SUBGRAPH VIEWER ====================
# with tab5:
#     st.markdown("## 🎯 Subgraph Viewer")
    
#     st.markdown("Explore a subgraph centered on a specific node")
    
#     # Search for center node
#     center_search = st.text_input("Search for center node:", 
#                                   placeholder="Enter node name or ID")
    
#     if center_search:
#         center_results = fuzzy_search_nodes(nodes_list, center_search)
#         if center_results:
#             center_node = st.selectbox(
#                 "Select center node:",
#                 options=range(len(center_results)),
#                 format_func=lambda i: f"{get_all_properties(center_results[i]).get('name', 'Unknown')} ({get_all_properties(center_results[i]).get('type', 'N/A')})"
#             )
            
#             max_depth = st.slider("Maximum depth (hops):", 1, 3, 1)
            
#             if st.button("Generate Subgraph"):
#                 center_id = center_results[center_node].get('id')
#                 sub_nodes, sub_edges = get_subgraph(center_id, nodes_list, edges_list, max_depth)
                
#                 st.success(f"Subgraph: {len(sub_nodes)} nodes, {len(sub_edges)} edges")
                
#                 create_network_graph(sub_nodes, sub_edges, height="600px")
    
#     # Check if coming from search tab
#     if st.session_state.get('subgraph_center'):
#         center_id = st.session_state['subgraph_center']
#         center_node = next((n for n in nodes_list if n.get('id') == center_id), None)
        
#         if center_node:
#             props = get_all_properties(center_node)
#             st.info(f"Showing subgraph for: **{props.get('name', center_id)}**")
            
#             max_depth = st.slider("Depth (hops):", 1, 3, 2, key="subgraph_depth")
            
#             sub_nodes, sub_edges = get_subgraph(center_id, nodes_list, edges_list, max_depth)
#             st.success(f"Subgraph: {len(sub_nodes)} nodes, {len(sub_edges)} edges")
            
#             create_network_graph(sub_nodes, sub_edges, height="600px")
            
#             if st.button("Clear Selection"):
#                 st.session_state['subgraph_center'] = None
#                 st.rerun()

# # ==================== TAB 6: ANALYTICS & EXPORT ====================
# with tab6:
#     st.markdown("## 📊 Advanced Analytics & Export")
    
#     # Analytics Section
#     st.markdown("### 📈 Graph Analytics")
    
#     # Most connected nodes
#     st.markdown("#### ⭐ Top 10 Most Connected Nodes")
    
#     if nodes_list and edges_list:
#         G_full = nx.DiGraph()
        
#         # Add nodes with validation
#         for node in nodes_list:
#             node_id = node.get('id')
#             if node_id is not None:
#                 G_full.add_node(node_id)
        
#         # Add edges with validation
#         for edge in edges_list:
#             src = edge.get('source_id')
#             tgt = edge.get('target_id')
#             if src is not None and tgt is not None and src in G_full.nodes and tgt in G_full.nodes:
#                 G_full.add_edge(src, tgt)
        
#         degrees = dict(G_full.degree())
#         top_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:10]
        
#         top_data = []
#         for node_id, degree in top_nodes:
#             node = next((n for n in nodes_list if n.get('id') == node_id), None)
#             if node:
#                 props = get_all_properties(node)
#                 top_data.append({
#                     'Node Name': props.get('name', node_id),
#                     'Type': props.get('type', 'Unknown'),
#                     'Connections': degree,
#                     'ID': node_id
#                 })
        
#         df_top = pd.DataFrame(top_data)
#         st.dataframe(df_top, use_container_width=True)
        
#         # Network metrics
#         st.markdown("#### 🕸️ Network Metrics")
#         col1, col2, col3, col4 = st.columns(4)
        
#         # Density
#         density = nx.density(G_full)
#         col1.metric("Network Density", f"{density:.4f}")
        
#         # Average degree
#         avg_degree = sum(degrees.values()) / len(degrees) if degrees else 0
#         col2.metric("Avg Degree", f"{avg_degree:.2f}")
        
#         # Connected components
#         num_components = nx.number_weakly_connected_components(G_full)
#         col3.metric("Connected Components", num_components)
        
#         # Diameter
#         try:
#             if nx.is_weakly_connected(G_full):
#                 diameter = nx.diameter(G_full.to_undirected())
#                 col4.metric("Network Diameter", diameter)
#             else:
#                 col4.metric("Network Diameter", "Disconnected")
#         except:
#             col4.metric("Network Diameter", "N/A")
        
#         # Relationship frequency
#         st.markdown("#### 🔀 Relationship Type Frequency")
#         rel_freq = pd.DataFrame(
#             [(t, c) for t, c in stats['edge_types'].items()],
#             columns=['Relationship Type', 'Count']
#         ).sort_values('Count', ascending=False)
        
#         fig_rel = px.bar(rel_freq, x='Relationship Type', y='Count',
#                         color='Count', color_continuous_scale='Blues',
#                         title='Relationship Types by Frequency')
#         fig_rel.update_layout(xaxis_tickangle=-45)
#         st.plotly_chart(fig_rel, use_container_width=True)
    
#     st.markdown("---")
    
#     # Export Section
#     st.markdown("### 💾 Export & Download")
    
#     col1, col2, col3 = st.columns(3)
    
#     with col1:
#         st.markdown("#### 📄 Export Node List")
#         if nodes_list:
#             # Prepare nodes CSV
#             nodes_export = []
#             for node in nodes_list:
#                 props = get_all_properties(node)
#                 nodes_export.append(props)
            
#             df_nodes = pd.DataFrame(nodes_export)
#             csv_nodes = df_nodes.to_csv(index=False)
            
#             st.download_button(
#                 label="📥 Download Nodes CSV",
#                 data=csv_nodes,
#                 file_name=f"{selected_graph}_nodes.csv",
#                 mime="text/csv",
#                 use_container_width=True
#             )
    
#     with col2:
#         st.markdown("#### 📄 Export Edge List")
#         if edges_list:
#             # Prepare edges CSV
#             edges_export = []
#             for edge in edges_list:
#                 props = get_all_properties(edge)
#                 edges_export.append(props)
            
#             df_edges = pd.DataFrame(edges_export)
#             csv_edges = df_edges.to_csv(index=False)
            
#             st.download_button(
#                 label="📥 Download Edges CSV",
#                 data=csv_edges,
#                 file_name=f"{selected_graph}_edges.csv",
#                 mime="text/csv",
#                 use_container_width=True
#             )
    
#     with col3:
#         st.markdown("#### 📄 Export Full Graph")
#         # Export as JSON
#         export_data = {
#             selected_graph: {
#                 "nodes": nodes_list,
#                 "edges": edges_list
#             }
#         }
        
#         json_export = json.dumps(export_data, indent=2)
        
#         st.download_button(
#             label="📥 Download Graph JSON",
#             data=json_export,
#             file_name=f"{selected_graph}_full.json",
#             mime="application/json",
#             use_container_width=True
#         )
    
#     # Generate Report
#     st.markdown("---")
#     st.markdown("### 📊 Generate Graph Report")
    
#     if st.button("📄 Generate Detailed Report", use_container_width=True):
#         report = f"""
# # Knowledge Graph Report: {selected_graph}
# Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

# ## Summary Statistics
# - Total Nodes: {stats['total_nodes']}
# - Total Edges: {stats['total_edges']}
# - Average Connections per Node: {stats['avg_connections']:.2f}
# - Isolated Nodes: {stats['isolated_nodes']}
# - Network Density: {density:.4f}
# - Connected Components: {num_components}

# ## Entity Types
# """
#         for etype, count in stats['node_types'].most_common():
#             report += f"- {etype}: {count}\n"
        
#         report += "\n## Relationship Types\n"
#         for rtype, count in stats['edge_types'].most_common():
#             report += f"- {rtype}: {count}\n"
        
#         report += "\n## Top 10 Most Connected Nodes\n"
#         for item in top_data:
#             report += f"- {item['Node Name']} ({item['Type']}): {item['Connections']} connections\n"
        
#         st.download_button(
#             label="📥 Download Report (Markdown)",
#             data=report,
#             file_name=f"{selected_graph}_report.md",
#             mime="text/markdown",
#             use_container_width=True
#         )
        
#         st.success("✅ Report generated successfully!")
#         with st.expander("📄 Preview Report"):
#             st.markdown(report)

# # ==================== MULTI-GRAPH COMPARISON (BONUS) ====================
# if len(graphs) > 1 and graphs[0] != "-":
#     st.markdown("---")
#     st.markdown("## 🔀 Multi-Graph Comparison")
    
#     with st.expander("Compare Multiple Graphs"):
#         st.markdown("Select 2-3 graphs to compare side by side")
        
#         selected_graphs_compare = st.multiselect(
#             "Select graphs to compare:",
#             options=[g for g in graphs if g != "-"],
#             max_selections=3
#         )
        
#         if len(selected_graphs_compare) >= 2:
#             comparison_data = []
            
#             for graph_name in selected_graphs_compare:
#                 g_nodes, g_edges = load_graph_data(graph_name)
#                 g_stats = get_graph_statistics(g_nodes, g_edges)
                
#                 comparison_data.append({
#                     'Graph': graph_name,
#                     'Nodes': g_stats['total_nodes'],
#                     'Edges': g_stats['total_edges'],
#                     'Avg Connections': f"{g_stats['avg_connections']:.2f}",
#                     'Isolated Nodes': g_stats['isolated_nodes'],
#                     'Node Types': len(g_stats['node_types']),
#                     'Edge Types': len(g_stats['edge_types'])
#                 })
            
#             df_compare = pd.DataFrame(comparison_data)
#             st.dataframe(df_compare, use_container_width=True)
            
#             # Comparison charts
#             col1, col2 = st.columns(2)
            
#             with col1:
#                 fig_comp_nodes = px.bar(df_compare, x='Graph', y='Nodes',
#                                        title='Node Count Comparison',
#                                        color='Nodes', color_continuous_scale='Viridis')
#                 st.plotly_chart(fig_comp_nodes, use_container_width=True)
            
#             with col2:
#                 fig_comp_edges = px.bar(df_compare, x='Graph', y='Edges',
#                                        title='Edge Count Comparison',
#                                        color='Edges', color_continuous_scale='Plasma')
#                 st.plotly_chart(fig_comp_edges, use_container_width=True)
            
#             # Entity type comparison
#             st.markdown("#### Entity Type Distribution Across Graphs")
            
#             all_entity_types = set()
#             entity_comparison = {}
            
#             for graph_name in selected_graphs_compare:
#                 g_nodes, g_edges = load_graph_data(graph_name)
#                 g_stats = get_graph_statistics(g_nodes, g_edges)
#                 entity_comparison[graph_name] = dict(g_stats['node_types'])
#                 all_entity_types.update(g_stats['node_types'].keys())
            
#             # Create comparison dataframe
#             entity_comp_data = []
#             for entity_type in all_entity_types:
#                 row = {'Entity Type': entity_type}
#                 for graph_name in selected_graphs_compare:
#                     row[graph_name] = entity_comparison[graph_name].get(entity_type, 0)
#                 entity_comp_data.append(row)
            
#             df_entity_comp = pd.DataFrame(entity_comp_data)
            
#             # Stacked bar chart
#             fig_entity = px.bar(df_entity_comp, x='Entity Type', 
#                                y=selected_graphs_compare,
#                                title='Entity Type Distribution (Stacked)',
#                                barmode='group')
#             fig_entity.update_layout(xaxis_tickangle=-45)
#             st.plotly_chart(fig_entity, use_container_width=True)

# # Footer
# st.markdown("---")
# st.markdown("""
# <div style="text-align: center; color: white; padding: 20px;">
#     <p>🧠 <b>Knowledge Graph Dashboard v1.0</b></p>
#     <p style="font-size: 12px;">
#         ✓ Interactive Visualization • ✓ Advanced Search • ✓ Analytics • ✓ Multi-Graph Support • ✓ Export Tools
#     </p>
#     <p style="font-size: 11px; margin-top: 10px;">
#         Built with Streamlit • FalkorDB • NetworkX • Plotly • PyVis
#     </p>
# </div>
# """, unsafe_allow_html=True)





# ======================================= more imporovement ==========================




# streamlit_kgraph_dashboard_complete.py
# Complete Knowledge Graph Dashboard - Meeting All Client Requirements
# Phases: Core Features, Advanced Features, Analytics & Polish + NLP Query Search

import os
import json
import tempfile
import re
import base64
from io import BytesIO
from typing import Tuple, List, Dict, Any, Optional, Set
from datetime import datetime
from collections import defaultdict, Counter

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx

# PyVis for interactive graphs
try:
    from pyvis.network import Network
    PYVIS_INSTALLED = True
except Exception:
    PYVIS_INSTALLED = False

# FalkorDB client
try:
    from falkordb import FalkorDB
except Exception:
    FalkorDB = None

# Page config
st.set_page_config(
    page_title="🧠 Knowledge Graph Dashboard",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    /* Main gradient background */
    .stApp {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    
    /* Sidebar - Clean white design */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
    }
    
    [data-testid="stSidebar"] .stMarkdown {
        color: #1f2937 !important;
    }
    
    [data-testid="stSidebar"] label {
        color: #1f2937 !important;
        font-weight: 600 !important;
    }
    
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] .stSelectbox {
        background: white !important;
        color: #1f2937 !important;
        border: 1px solid #d1d5db !important;
        border-radius: 8px !important;
    }
    
    [data-testid="stSidebar"] .stSelectbox > div {
        background: white !important;
        color: #1f2937 !important;
    }
    
    [data-testid="stSidebar"] .stNumberInput input,
    [data-testid="stSidebar"] .stTextInput input {
        background: white !important;
        color: #1f2937 !important;
    }
    
    [data-testid="stSidebar"] .stFileUploader {
        background: white !important;
        border: 2px dashed #667eea !important;
        border-radius: 8px !important;
        padding: 10px !important;
    }
    
    [data-testid="stSidebar"] hr {
        border-color: #d1d5db !important;
    }
    
    /* Card styling */
    .metric-card {
        background: rgba(255, 255, 255, 0.95);
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.2);
    }
    
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 30px;
        border-radius: 20px;
        color: white;
        text-align: center;
        margin-bottom: 30px;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
    }
    
    .stButton button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 25px;
        padding: 10px 30px;
        border: none;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
    }
    
    .node-card {
        background: white;
        padding: 20px;
        border-radius: 15px;
        margin: 10px 0;
        box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
        border-left: 4px solid #667eea;
    }
    
    .property-badge {
        display: inline-block;
        background: #e0e7ff;
        padding: 4px 12px;
        border-radius: 12px;
        margin: 3px;
        font-size: 13px;
        color: #4338ca;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
    <h1>🧠 Knowledge Graph Dashboard</h1>
    <p style="font-size: 18px; margin-top: 10px;">Comprehensive Graph Analysis & Visualization Platform</p>
</div>
""", unsafe_allow_html=True)

# Initialize session state
if "pyvis_disabled" not in st.session_state:
    st.session_state["pyvis_disabled"] = False
if "selected_node" not in st.session_state:
    st.session_state["selected_node"] = None
if "subgraph_center" not in st.session_state:
    st.session_state["subgraph_center"] = None

# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("### 🔌 Connection Settings")
    host = st.text_input("Host", value="localhost", help="FalkorDB host address")
    port = st.number_input("Port", value=6379, step=1, help="FalkorDB port number")
    
    connect_btn = st.button("🔗 Connect to FalkorDB", use_container_width=True)
    
    st.markdown("---")
    st.markdown("### 📁 Local Data (Optional)")
    json_file = st.file_uploader("Upload JSON Export", type=["json"], 
                                 help="Upload your knowledge graph JSON file")
    
    st.markdown("---")
    st.markdown("### ℹ️ About")
    st.caption("**Version:** 1.0.0")
    st.caption("**Features:**")
    st.caption("✓ Interactive Graph Visualization")
    st.caption("✓ Node Search & Exploration")
    st.caption("✓ Natural Language Query")
    st.caption("✓ Advanced Analytics")
    st.caption("✓ Multi-Graph Comparison")
    st.caption("✓ Export & Download")

# ==================== DATABASE CONNECTION ====================
@st.cache_resource
def get_db(host: str, port: int):
    if FalkorDB is None:
        return None
    try:
        return FalkorDB(host=host, port=port)
    except Exception:
        return None

db = get_db(host, port) if connect_btn else None

# Load local JSON
local_data: Dict[str, Any] = {}
if json_file is not None:
    try:
        local_data = json.load(json_file)
        st.sidebar.success("✅ JSON loaded successfully!")
    except Exception as e:
        st.sidebar.error(f"❌ Failed to load JSON: {e}")

# Get available graphs
graphs: List[str] = []
if local_data:
    graphs = list(local_data.keys())
elif db is not None:
    try:
        graphs = db.list_graphs()
        if graphs:
            st.sidebar.success(f"✅ Connected! Found {len(graphs)} graphs")
    except Exception as e:
        st.sidebar.error(f"❌ Connection failed: {e}")
        graphs = []

if not graphs:
    graphs = ["-"]

# ==================== HELPER FUNCTIONS ====================

def get_all_properties(item: Dict) -> Dict[str, Any]:
    """Extract all properties from a node/edge"""
    all_props = {}
    for key, value in item.items():
        if key != 'properties':
            all_props[key] = value
    if 'properties' in item:
        all_props.update(item['properties'])
    return all_props

def safe_query(graph, cypher: str, params: Dict = None):
    """Execute Cypher query safely"""
    try:
        result = graph.query(cypher, params or {})
        rows = getattr(result, "result_set", None)
        return rows if rows is not None else []
    except Exception as e:
        st.warning(f"Query error: {e}")
        return []

@st.cache_data(ttl=300)
def load_graph_data(graph_name: str):
    """Load graph data from JSON or DB"""
    nodes_list = []
    edges_list = []
    
    if local_data:
        g = local_data.get(graph_name, {})
        nodes_list = g.get("nodes", [])
        edges_list = g.get("edges", [])
    elif db is not None and graph_name != "-":
        try:
            g = db.select_graph(graph_name)
            # Fetch nodes
            node_rows = safe_query(g, "MATCH (n) RETURN n.id, n.name, n.type, n.label, properties(n) LIMIT 1000")
            for row in node_rows:
                nodes_list.append({
                    'id': row[0],
                    'name': row[1],
                    'type': row[2],
                    'label': row[3],
                    'properties': row[4] if len(row) > 4 else {}
                })
            # Fetch edges
            edge_rows = safe_query(g, "MATCH (a)-[r]->(b) RETURN r.id, type(r), a.id, b.id, r.confidence, properties(r) LIMIT 2000")
            for row in edge_rows:
                edges_list.append({
                    'id': row[0],
                    'type': row[1],
                    'source_id': row[2],
                    'target_id': row[3],
                    'confidence': row[4] if len(row) > 4 else None,
                    'properties': row[5] if len(row) > 5 else {}
                })
        except Exception as e:
            st.error(f"Error loading graph: {e}")
    
    return nodes_list, edges_list

def get_graph_statistics(nodes: List[Dict], edges: List[Dict]) -> Dict:
    """Calculate graph statistics"""
    stats = {
        'total_nodes': len(nodes),
        'total_edges': len(edges),
        'node_types': Counter(),
        'edge_types': Counter(),
        'avg_connections': 0,
        'isolated_nodes': 0
    }
    
    # Count types
    for node in nodes:
        props = get_all_properties(node)
        ntype = props.get('type', 'Unknown')
        stats['node_types'][ntype] += 1
    
    for edge in edges:
        props = get_all_properties(edge)
        etype = props.get('type', 'Unknown')
        stats['edge_types'][etype] += 1
    
    # Calculate connectivity
    if nodes:
        stats['avg_connections'] = len(edges) / len(nodes)
    
    # Find isolated nodes - with validation
    connected_nodes = set()
    for edge in edges:
        src = edge.get('source_id')
        tgt = edge.get('target_id')
        # Only add if not None
        if src is not None:
            connected_nodes.add(src)
        if tgt is not None:
            connected_nodes.add(tgt)
    
    stats['isolated_nodes'] = len(nodes) - len(connected_nodes)
    
    return stats

def fuzzy_search_nodes(nodes: List[Dict], query: str) -> List[Dict]:
    """Fuzzy search for nodes"""
    query_lower = query.lower()
    results = []
    
    for node in nodes:
        props = get_all_properties(node)
        # Search in name, id, type
        searchable = f"{props.get('name', '')} {props.get('id', '')} {props.get('type', '')}".lower()
        if query_lower in searchable:
            results.append(node)
    
    return results

def query_graph_nlp(query: str, nodes: List[Dict], edges: List[Dict]) -> Tuple[List[Dict], List[Dict], List[str]]:
    """
    Natural language query search across the graph
    Returns: (matching_nodes, relevant_edges, keywords_found)
    """
    # Extract keywords from query (simple tokenization)
    query_lower = query.lower()
    
    # Remove common stop words
    stop_words = {'what', 'was', 'my', 'the', 'is', 'are', 'when', 'where', 'who', 
                  'how', 'did', 'do', 'does', 'a', 'an', 'and', 'or', 'but', 'in', 
                  'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    
    # Extract keywords
    words = re.findall(r'\b\w+\b', query_lower)
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    
    # Score nodes based on keyword matches
    node_scores = {}
    keywords_found = set()
    
    for node in nodes:
        props = get_all_properties(node)
        node_id = props.get('id')
        if node_id is None:
            continue
            
        score = 0
        # Search in all properties
        searchable_text = ' '.join([str(v).lower() for v in props.values() if v]).replace('_', ' ')
        
        for keyword in keywords:
            if keyword in searchable_text:
                score += searchable_text.count(keyword)
                keywords_found.add(keyword)
        
        if score > 0:
            node_scores[node_id] = score
    
    # Get matching nodes (sorted by score)
    matching_node_ids = sorted(node_scores.keys(), key=lambda x: node_scores[x], reverse=True)
    matching_nodes = [n for n in nodes if n.get('id') in matching_node_ids]
    
    # Get edges connecting matching nodes
    relevant_edges = []
    for edge in edges:
        src = edge.get('source_id')
        tgt = edge.get('target_id')
        
        if src is None or tgt is None:
            continue
            
        # Include edge if it connects any matching nodes
        if src in matching_node_ids or tgt in matching_node_ids:
            relevant_edges.append(edge)
    
    return matching_nodes, relevant_edges, list(keywords_found)

def get_node_neighbors(node_id: str, nodes: List[Dict], edges: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Get all neighbors and relationships for a node"""
    neighbors = []
    relationships = []
    
    for edge in edges:
        src = edge.get('source_id')
        tgt = edge.get('target_id')
        
        # Skip edges with None values
        if src is None or tgt is None:
            continue
            
        if src == node_id or tgt == node_id:
            relationships.append(edge)
            # Get neighbor
            neighbor_id = tgt if src == node_id else src
            neighbor = next((n for n in nodes if n.get('id') == neighbor_id), None)
            if neighbor:
                neighbors.append(neighbor)
    
    return neighbors, relationships

def get_subgraph(center_node_id: str, nodes: List[Dict], edges: List[Dict], max_depth: int = 1) -> Tuple[List[Dict], List[Dict]]:
    """Get subgraph within N hops from center node"""
    subgraph_nodes = set([center_node_id])
    subgraph_edges = []
    
    current_level = set([center_node_id])
    
    for depth in range(max_depth):
        next_level = set()
        for node_id in current_level:
            for edge in edges:
                src = edge.get('source_id')
                tgt = edge.get('target_id')
                
                # Skip edges with None values
                if src is None or tgt is None:
                    continue
                
                if src == node_id:
                    next_level.add(tgt)
                    if edge not in subgraph_edges:
                        subgraph_edges.append(edge)
                elif tgt == node_id:
                    next_level.add(src)
                    if edge not in subgraph_edges:
                        subgraph_edges.append(edge)
        
        subgraph_nodes.update(next_level)
        current_level = next_level
    
    subgraph_nodes_list = [n for n in nodes if n.get('id') in subgraph_nodes]
    
    return subgraph_nodes_list, subgraph_edges

def create_network_graph(nodes: List[Dict], edges: List[Dict], height: str = "700px", show_labels: bool = True):
    """Create interactive network visualization"""
    if not nodes:
        st.info("No nodes to visualize")
        return
    
    G = nx.DiGraph()
    
    # Add nodes
    for node in nodes:
        props = get_all_properties(node)
        nid = props.get('id')
        if nid is None:
            continue  # Skip nodes without ID
        name = props.get('name', nid)
        ntype = props.get('type', 'Node')
        G.add_node(nid, label=name, ntype=ntype, props=props)
    
    # Add edges - with validation
    for edge in edges:
        props = get_all_properties(edge)
        src = props.get('source_id')
        tgt = props.get('target_id')
        
        # Skip if source or target is None or not in nodes
        if src is None or tgt is None:
            continue
        if src not in G.nodes or tgt not in G.nodes:
            continue
            
        G.add_edge(src, tgt, etype=props.get('type', 'RELATED'), props=props)
    
    # Try PyVis first
    if PYVIS_INSTALLED and not st.session_state.get('pyvis_disabled'):
        try:
            net = Network(height=height, width="100%", directed=True, 
                         bgcolor="#f8f9fa", font_color="#333")
            
            # Color palette for different types
            colors = ['#667eea', '#764ba2', '#f093fb', '#4facfe', 
                     '#43e97b', '#fa709a', '#fee140', '#30cfd0']
            
            type_colors = {}
            for node, data in G.nodes(data=True):
                ntype = data.get('ntype', 'Node')
                if ntype not in type_colors:
                    type_colors[ntype] = colors[len(type_colors) % len(colors)]
                
                props = data.get('props', {})
                title = f"<b>{data.get('label', node)}</b><br>Type: {ntype}<br>ID: {node}"
                
                net.add_node(
                    node,
                    label=data.get('label', node) if show_labels else '',
                    title=title,
                    color=type_colors[ntype],
                    size=25
                )
            
            for u, v, data in G.edges(data=True):
                etype = data.get('etype', 'RELATED')
                net.add_edge(u, v, title=etype, color='#cccccc', width=2)
            
            net.set_options("""
            {
                "physics": {
                    "forceAtlas2Based": {
                        "gravitationalConstant": -50,
                        "centralGravity": 0.01,
                        "springLength": 200,
                        "springConstant": 0.08
                    },
                    "maxVelocity": 50,
                    "solver": "forceAtlas2Based",
                    "timestep": 0.35,
                    "stabilization": {"iterations": 150}
                }
            }
            """)
            
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
            net.save_graph(tmp.name)
            
            with open(tmp.name, 'r', encoding='utf-8') as f:
                html = f.read()
            
            st.components.v1.html(html, height=int(height.replace('px', '')), scrolling=True)
            os.unlink(tmp.name)
            return
            
        except Exception as e:
            st.session_state['pyvis_disabled'] = True
            st.warning(f"PyVis failed, using fallback: {e}")
    
    # Fallback to Plotly
    pos = nx.spring_layout(G, seed=42, k=2)
    
    edge_x, edge_y = [], []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
    
    node_x, node_y, labels = [], [], []
    for n, data in G.nodes(data=True):
        x, y = pos[n]
        node_x.append(x)
        node_y.append(y)
        labels.append(data.get('label', n))
    
    edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines", 
                           line=dict(width=1, color="#ccc"), hoverinfo="none")
    node_trace = go.Scatter(x=node_x, y=node_y, mode="markers+text", 
                           text=labels if show_labels else None,
                           textposition="top center",
                           marker=dict(size=15, color='#667eea'),
                           hoverinfo="text", hovertext=labels)
    
    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        showlegend=False,
        height=int(height.replace('px', '')),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        plot_bgcolor='#f8f9fa'
    )
    st.plotly_chart(fig, use_container_width=True)

# ==================== MAIN CONTENT ====================

# Graph selector in main area (not sidebar as per requirements)
st.markdown("### 📊 Select Knowledge Graph")
selected_graph = st.selectbox(
    "Choose a graph to explore:",
    options=graphs,
    index=0,
    help="Select from available knowledge graphs"
)

if selected_graph == "-":
    st.info("👈 Please upload a JSON file or connect to FalkorDB to get started")
    st.stop()

# Load graph data
nodes_list, edges_list = load_graph_data(selected_graph)

if not nodes_list:
    st.warning("No data found in selected graph")
    st.stop()

# Calculate statistics
stats = get_graph_statistics(nodes_list, edges_list)

# ==================== TABS ====================
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📈 Overview",
    "🔍 Node Search",
    "💬 Query Search",
    "🌐 Graph Visualization", 
    "🔗 Relationship Explorer",
    "🎯 Subgraph Viewer",
    "📊 Analytics & Export"
])

# ==================== TAB 1: OVERVIEW ====================
with tab1:
    st.markdown(f"## Graph Overview: {selected_graph}")
    
    # Statistics cards
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔵 Total Nodes", stats['total_nodes'])
    col2.metric("🔗 Total Edges", stats['total_edges'])
    col3.metric("📊 Avg Connections", f"{stats['avg_connections']:.2f}")
    col4.metric("⚪ Isolated Nodes", stats['isolated_nodes'])
    
    st.markdown("---")
    
    # Charts
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Entity Type Distribution")
        if stats['node_types']:
            df_types = pd.DataFrame(
                [(t, c) for t, c in stats['node_types'].items()],
                columns=['Type', 'Count']
            ).sort_values('Count', ascending=False)
            
            fig = px.bar(df_types, x='Type', y='Count',
                        color='Count', color_continuous_scale='Viridis',
                        title='Nodes by Entity Type')
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No entity type data available")
    
    with col2:
        st.markdown("#### Relationship Type Distribution")
        if stats['edge_types']:
            df_edges = pd.DataFrame(
                [(t, c) for t, c in stats['edge_types'].items()],
                columns=['Relationship', 'Count']
            ).sort_values('Count', ascending=False)
            
            fig2 = px.pie(df_edges, values='Count', names='Relationship',
                         title='Relationships by Type',
                         color_discrete_sequence=px.colors.sequential.RdBu)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No relationship data available")

# ==================== TAB 2: NODE SEARCH ====================
with tab2:
    st.markdown("## 🔍 Node Search & Exploration")
    
    search_query = st.text_input(
        "Search nodes by name, ID, or type:",
        placeholder="e.g., blood_pressure, user, fitbit...",
        help="Fuzzy search across node properties"
    )
    
    if search_query:
        results = fuzzy_search_nodes(nodes_list, search_query)
        
        if results:
            st.success(f"Found {len(results)} matching nodes")
            
            for idx, node in enumerate(results[:20]):  # Limit to 20 results
                props = get_all_properties(node)
                node_id = props.get('id')
                node_name = props.get('name', node_id)
                node_type = props.get('type', 'Unknown')
                
                with st.expander(f"📌 {node_name} ({node_type})"):
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        st.markdown("**Properties:**")
                        for key, value in props.items():
                            if key not in ['id', 'properties'] and value:
                                st.write(f"• **{key}:** {value}")
                    
                    with col2:
                        if st.button(f"View Neighbors", key=f"view_{idx}"):
                            st.session_state['selected_node'] = node_id
                    
                    # Show neighbors if selected
                    if st.session_state.get('selected_node') == node_id:
                        neighbors, relationships = get_node_neighbors(node_id, nodes_list, edges_list)
                        
                        st.markdown(f"**🔗 Connected Nodes ({len(neighbors)}):**")
                        for neighbor in neighbors[:10]:
                            n_props = get_all_properties(neighbor)
                            st.write(f"→ {n_props.get('name', n_props.get('id'))} ({n_props.get('type', 'N/A')})")
                        
                        st.markdown(f"**🔀 Relationships ({len(relationships)}):**")
                        for rel in relationships[:10]:
                            r_props = get_all_properties(rel)
                            st.write(f"• {r_props.get('type', 'RELATED')} (confidence: {r_props.get('confidence', 'N/A')})")
                        
                        if st.button(f"Expand to Subgraph", key=f"expand_{idx}"):
                            st.session_state['subgraph_center'] = node_id
                            st.info("Go to 'Subgraph Viewer' tab to see the expanded view")
        else:
            st.warning("No nodes found matching your search")

# ==================== TAB 3: QUERY SEARCH ====================
with tab3:
    st.markdown("## 💬 Natural Language Query Search")
    st.markdown("Ask questions about your knowledge graph in natural language")
    
    # Example queries
    with st.expander("📝 Example Queries"):
        st.markdown("""
        Try asking questions like:
        - "What was my blood pressure last night?"
        - "Show me all fitness data"
        - "Find heart rate measurements"
        - "What devices are connected to user?"
        - "Show omron monitor data"
        """)
    
    nl_query = st.text_input(
        "Ask a question:",
        placeholder="e.g., What was my blood pressure last night?",
        help="Ask natural language questions about your graph data",
        key="nl_query_input"
    )
    
    if nl_query:
        with st.spinner("🔍 Searching graph..."):
            matching_nodes, relevant_edges, keywords = query_graph_nlp(nl_query, nodes_list, edges_list)
        
        if matching_nodes:
            # Show summary
            col1, col2, col3 = st.columns(3)
            col1.metric("📊 Matching Nodes", len(matching_nodes))
            col2.metric("🔗 Related Edges", len(relevant_edges))
            col3.metric("🔑 Keywords Found", len(keywords))
            
            if keywords:
                st.info(f"**Keywords detected:** {', '.join(keywords)}")
            
            st.markdown("---")
            
            # Display results in two columns
            col_left, col_right = st.columns([1, 1])
            
            with col_left:
                st.markdown("### 📌 Matching Entities")
                
                for idx, node in enumerate(matching_nodes[:15]):  # Top 15 results
                    props = get_all_properties(node)
                    node_id = props.get('id')
                    node_name = props.get('name', node_id)
                    node_type = props.get('type', 'Unknown')
                    
                    with st.expander(f"🔹 {node_name} ({node_type})", expanded=(idx < 3)):
                        st.markdown("**Properties:**")
                        
                        # Highlight matching properties
                        for key, value in props.items():
                            if key not in ['id', 'properties'] and value:
                                value_str = str(value).lower()
                                is_match = any(k in value_str for k in keywords)
                                
                                if is_match:
                                    st.markdown(f"🔸 **{key}:** `{value}` ⭐")
                                else:
                                    st.write(f"• **{key}:** {value}")
                        
                        # Quick actions
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("View Network", key=f"nlp_view_{idx}"):
                                st.session_state['selected_node'] = node_id
                                st.session_state['subgraph_center'] = node_id
                        with col_b:
                            if st.button("Relationships", key=f"nlp_rel_{idx}"):
                                neighbors, relationships = get_node_neighbors(node_id, nodes_list, edges_list)
                                st.markdown(f"**Connected to {len(neighbors)} nodes via {len(relationships)} relationships**")
            
            with col_right:
                st.markdown("### 🌐 Visual Overview")
                
                # Create visualization of query results
                if len(matching_nodes) <= 50:  # Reasonable limit for visualization
                    st.markdown("**Interactive graph of query results:**")
                    create_network_graph(matching_nodes, relevant_edges, height="500px", show_labels=True)
                else:
                    st.warning(f"Too many nodes ({len(matching_nodes)}) to visualize. Showing top 50.")
                    create_network_graph(matching_nodes[:50], relevant_edges, height="500px", show_labels=True)
                
                # Relationship summary
                st.markdown("---")
                st.markdown("### 🔗 Relationship Summary")
                
                if relevant_edges:
                    rel_types = Counter([get_all_properties(e).get('type', 'Unknown') for e in relevant_edges])
                    
                    rel_df = pd.DataFrame([
                        {'Relationship': rel, 'Count': count} 
                        for rel, count in rel_types.most_common()
                    ])
                    
                    fig_rel_pie = px.pie(
                        rel_df, 
                        values='Count', 
                        names='Relationship',
                        title='Relationship Types in Results',
                        color_discrete_sequence=px.colors.sequential.Purples
                    )
                    st.plotly_chart(fig_rel_pie, use_container_width=True)
                else:
                    st.info("No relationships found between matching nodes")
            
            # Detailed relationship table
            st.markdown("---")
            st.markdown("### 📋 Detailed Connections")
            
            if relevant_edges:
                connection_data = []
                for edge in relevant_edges[:50]:  # Limit to 50
                    e_props = get_all_properties(edge)
                    src_node = next((n for n in nodes_list if n.get('id') == e_props.get('source_id')), None)
                    tgt_node = next((n for n in nodes_list if n.get('id') == e_props.get('target_id')), None)
                    
                    if src_node and tgt_node:
                        src_props = get_all_properties(src_node)
                        tgt_props = get_all_properties(tgt_node)
                        
                        connection_data.append({
                            'From': src_props.get('name', src_props.get('id')),
                            'Relationship': e_props.get('type', 'RELATED'),
                            'To': tgt_props.get('name', tgt_props.get('id')),
                            'Confidence': e_props.get('confidence', 'N/A')
                        })
                
                if connection_data:
                    df_connections = pd.DataFrame(connection_data)
                    st.dataframe(df_connections, use_container_width=True, height=300)
            
            # Export query results
            st.markdown("---")
            if st.button("💾 Export Query Results", use_container_width=True):
                result_export = {
                    "query": nl_query,
                    "keywords": keywords,
                    "timestamp": datetime.now().isoformat(),
                    "matching_nodes": [get_all_properties(n) for n in matching_nodes],
                    "relevant_edges": [get_all_properties(e) for e in relevant_edges]
                }
                
                json_result = json.dumps(result_export, indent=2)
                st.download_button(
                    label="📥 Download Results (JSON)",
                    data=json_result,
                    file_name=f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )
        else:
            st.warning("⚠️ No results found for your query")
            st.info("💡 **Tips:**\n- Try using different keywords\n- Check spelling\n- Use simpler terms\n- Try searching for entity types (e.g., 'blood pressure', 'user', 'device')")

# ==================== TAB 4: GRAPH VISUALIZATION ====================
with tab4:
    st.markdown("## 🌐 Interactive Graph Visualization")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        viz_limit = st.slider("Number of nodes to display:", 10, 200, 50, 10)
    with col2:
        show_labels = st.checkbox("Show node labels", value=True)
    
    st.info(f"Displaying top {viz_limit} most connected nodes for performance")
    
    # Get top connected nodes
    if nodes_list and edges_list:
        G_temp = nx.DiGraph()
        
        # Add all nodes
        for node in nodes_list:
            node_id = node.get('id')
            if node_id is not None:
                G_temp.add_node(node_id)
        
        # Add edges with validation
        for edge in edges_list:
            src = edge.get('source_id')
            tgt = edge.get('target_id')
            # Only add edge if both nodes exist and are not None
            if src is not None and tgt is not None and src in G_temp.nodes and tgt in G_temp.nodes:
                G_temp.add_edge(src, tgt)
        
        degrees = dict(G_temp.degree())
        top_nodes = sorted(degrees, key=lambda x: degrees[x], reverse=True)[:viz_limit]
        
        viz_nodes = [n for n in nodes_list if n.get('id') in top_nodes]
        viz_edges = [e for e in edges_list if e.get('source_id') in top_nodes and e.get('target_id') in top_nodes]
        
        create_network_graph(viz_nodes, viz_edges, height="700px", show_labels=show_labels)

# ==================== TAB 5: RELATIONSHIP EXPLORER ====================
with tab5:
    st.markdown("## 🔗 Relationship Explorer")
    
    # Get all relationship types
    rel_types = list(stats['edge_types'].keys())
    
    if rel_types:
        selected_rel = st.selectbox("Select relationship type:", rel_types)
        
        # Filter edges by type
        filtered_edges = [e for e in edges_list if get_all_properties(e).get('type') == selected_rel]
        
        st.metric("Relationships found:", len(filtered_edges))
        
        if filtered_edges:
            # Create table
            table_data = []
            for edge in filtered_edges[:100]:  # Limit to 100
                props = get_all_properties(edge)
                src_node = next((n for n in nodes_list if n.get('id') == props.get('source_id')), None)
                tgt_node = next((n for n in nodes_list if n.get('id') == props.get('target_id')), None)
                
                if src_node and tgt_node:
                    src_props = get_all_properties(src_node)
                    tgt_props = get_all_properties(tgt_node)
                    
                    table_data.append({
                        'Source': src_props.get('name', src_props.get('id')),
                        'Source Type': src_props.get('type', 'N/A'),
                        'Relationship': selected_rel,
                        'Target': tgt_props.get('name', tgt_props.get('id')),
                        'Target Type': tgt_props.get('type', 'N/A'),
                        'Confidence': props.get('confidence', 'N/A')
                    })
            
            df_rel = pd.DataFrame(table_data)
            st.dataframe(df_rel, use_container_width=True)
    else:
        st.info("No relationship types found")

# ==================== TAB 6: SUBGRAPH VIEWER ====================
with tab6:
    st.markdown("## 🎯 Subgraph Viewer")
    
    st.markdown("Explore a subgraph centered on a specific node")
    
    # Search for center node
    center_search = st.text_input("Search for center node:", 
                                  placeholder="Enter node name or ID")
    
    if center_search:
        center_results = fuzzy_search_nodes(nodes_list, center_search)
        if center_results:
            center_node = st.selectbox(
                "Select center node:",
                options=range(len(center_results)),
                format_func=lambda i: f"{get_all_properties(center_results[i]).get('name', 'Unknown')} ({get_all_properties(center_results[i]).get('type', 'N/A')})"
            )
            
            max_depth = st.slider("Maximum depth (hops):", 1, 3, 1)
            
            if st.button("Generate Subgraph"):
                center_id = center_results[center_node].get('id')
                sub_nodes, sub_edges = get_subgraph(center_id, nodes_list, edges_list, max_depth)
                
                st.success(f"Subgraph: {len(sub_nodes)} nodes, {len(sub_edges)} edges")
                
                create_network_graph(sub_nodes, sub_edges, height="600px")
    
    # Check if coming from search tab
    if st.session_state.get('subgraph_center'):
        center_id = st.session_state['subgraph_center']
        center_node = next((n for n in nodes_list if n.get('id') == center_id), None)
        
        if center_node:
            props = get_all_properties(center_node)
            st.info(f"Showing subgraph for: **{props.get('name', center_id)}**")
            
            max_depth = st.slider("Depth (hops):", 1, 3, 2, key="subgraph_depth")
            
            sub_nodes, sub_edges = get_subgraph(center_id, nodes_list, edges_list, max_depth)
            st.success(f"Subgraph: {len(sub_nodes)} nodes, {len(sub_edges)} edges")
            
            create_network_graph(sub_nodes, sub_edges, height="600px")
            
            if st.button("Clear Selection"):
                st.session_state['subgraph_center'] = None
                st.rerun()

# ==================== TAB 7: ANALYTICS & EXPORT ====================
with tab7:
    st.markdown("## 📊 Advanced Analytics & Export")
    
    # Analytics Section
    st.markdown("### 📈 Graph Analytics")
    
    # Most connected nodes
    st.markdown("#### ⭐ Top 10 Most Connected Nodes")
    
    if nodes_list and edges_list:
        G_full = nx.DiGraph()
        
        # Add nodes with validation
        for node in nodes_list:
            node_id = node.get('id')
            if node_id is not None:
                G_full.add_node(node_id)
        
        # Add edges with validation
        for edge in edges_list:
            src = edge.get('source_id')
            tgt = edge.get('target_id')
            if src is not None and tgt is not None and src in G_full.nodes and tgt in G_full.nodes:
                G_full.add_edge(src, tgt)
        
        degrees = dict(G_full.degree())
        top_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:10]
        
        top_data = []
        for node_id, degree in top_nodes:
            node = next((n for n in nodes_list if n.get('id') == node_id), None)
            if node:
                props = get_all_properties(node)
                top_data.append({
                    'Node Name': props.get('name', node_id),
                    'Type': props.get('type', 'Unknown'),
                    'Connections': degree,
                    'ID': node_id
                })
        
        df_top = pd.DataFrame(top_data)
        st.dataframe(df_top, use_container_width=True)
        
        # Network metrics
        st.markdown("#### 🕸️ Network Metrics")
        col1, col2, col3, col4 = st.columns(4)
        
        # Density
        density = nx.density(G_full)
        col1.metric("Network Density", f"{density:.4f}")
        
        # Average degree
        avg_degree = sum(degrees.values()) / len(degrees) if degrees else 0
        col2.metric("Avg Degree", f"{avg_degree:.2f}")
        
        # Connected components
        num_components = nx.number_weakly_connected_components(G_full)
        col3.metric("Connected Components", num_components)
        
        # Diameter
        try:
            if nx.is_weakly_connected(G_full):
                diameter = nx.diameter(G_full.to_undirected())
                col4.metric("Network Diameter", diameter)
            else:
                col4.metric("Network Diameter", "Disconnected")
        except:
            col4.metric("Network Diameter", "N/A")
        
        # Relationship frequency
        st.markdown("#### 🔀 Relationship Type Frequency")
        rel_freq = pd.DataFrame(
            [(t, c) for t, c in stats['edge_types'].items()],
            columns=['Relationship Type', 'Count']
        ).sort_values('Count', ascending=False)
        
        fig_rel = px.bar(rel_freq, x='Relationship Type', y='Count',
                        color='Count', color_continuous_scale='Blues',
                        title='Relationship Types by Frequency')
        fig_rel.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_rel, use_container_width=True)
    
    st.markdown("---")
    
    # Export Section
    st.markdown("### 💾 Export & Download")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### 📄 Export Node List")
        if nodes_list:
            # Prepare nodes CSV
            nodes_export = []
            for node in nodes_list:
                props = get_all_properties(node)
                nodes_export.append(props)
            
            df_nodes = pd.DataFrame(nodes_export)
            csv_nodes = df_nodes.to_csv(index=False)
            
            st.download_button(
                label="📥 Download Nodes CSV",
                data=csv_nodes,
                file_name=f"{selected_graph}_nodes.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    with col2:
        st.markdown("#### 📄 Export Edge List")
        if edges_list:
            # Prepare edges CSV
            edges_export = []
            for edge in edges_list:
                props = get_all_properties(edge)
                edges_export.append(props)
            
            df_edges = pd.DataFrame(edges_export)
            csv_edges = df_edges.to_csv(index=False)
            
            st.download_button(
                label="📥 Download Edges CSV",
                data=csv_edges,
                file_name=f"{selected_graph}_edges.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    with col3:
        st.markdown("#### 📄 Export Full Graph")
        # Export as JSON
        export_data = {
            selected_graph: {
                "nodes": nodes_list,
                "edges": edges_list
            }
        }
        
        json_export = json.dumps(export_data, indent=2)
        
        st.download_button(
            label="📥 Download Graph JSON",
            data=json_export,
            file_name=f"{selected_graph}_full.json",
            mime="application/json",
            use_container_width=True
        )
    
    # Generate Report
    st.markdown("---")
    st.markdown("### 📊 Generate Graph Report")
    
    if st.button("📄 Generate Detailed Report", use_container_width=True):
        report = f"""
# Knowledge Graph Report: {selected_graph}
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary Statistics
- Total Nodes: {stats['total_nodes']}
- Total Edges: {stats['total_edges']}
- Average Connections per Node: {stats['avg_connections']:.2f}
- Isolated Nodes: {stats['isolated_nodes']}
- Network Density: {density:.4f}
- Connected Components: {num_components}

## Entity Types
"""
        for etype, count in stats['node_types'].most_common():
            report += f"- {etype}: {count}\n"
        
        report += "\n## Relationship Types\n"
        for rtype, count in stats['edge_types'].most_common():
            report += f"- {rtype}: {count}\n"
        
        report += "\n## Top 10 Most Connected Nodes\n"
        for item in top_data:
            report += f"- {item['Node Name']} ({item['Type']}): {item['Connections']} connections\n"
        
        st.download_button(
            label="📥 Download Report (Markdown)",
            data=report,
            file_name=f"{selected_graph}_report.md",
            mime="text/markdown",
            use_container_width=True
        )
        
        st.success("✅ Report generated successfully!")
        with st.expander("📄 Preview Report"):
            st.markdown(report)

# ==================== MULTI-GRAPH COMPARISON (BONUS) ====================
if len(graphs) > 1 and graphs[0] != "-":
    st.markdown("---")
    st.markdown("## 🔀 Multi-Graph Comparison")
    
    with st.expander("Compare Multiple Graphs"):
        st.markdown("Select 2-3 graphs to compare side by side")
        
        selected_graphs_compare = st.multiselect(
            "Select graphs to compare:",
            options=[g for g in graphs if g != "-"],
            max_selections=3
        )
        
        if len(selected_graphs_compare) >= 2:
            comparison_data = []
            
            for graph_name in selected_graphs_compare:
                g_nodes, g_edges = load_graph_data(graph_name)
                g_stats = get_graph_statistics(g_nodes, g_edges)
                
                comparison_data.append({
                    'Graph': graph_name,
                    'Nodes': g_stats['total_nodes'],
                    'Edges': g_stats['total_edges'],
                    'Avg Connections': f"{g_stats['avg_connections']:.2f}",
                    'Isolated Nodes': g_stats['isolated_nodes'],
                    'Node Types': len(g_stats['node_types']),
                    'Edge Types': len(g_stats['edge_types'])
                })
            
            df_compare = pd.DataFrame(comparison_data)
            st.dataframe(df_compare, use_container_width=True)
            
            # Comparison charts
            col1, col2 = st.columns(2)
            
            with col1:
                fig_comp_nodes = px.bar(df_compare, x='Graph', y='Nodes',
                                       title='Node Count Comparison',
                                       color='Nodes', color_continuous_scale='Viridis')
                st.plotly_chart(fig_comp_nodes, use_container_width=True)
            
            with col2:
                fig_comp_edges = px.bar(df_compare, x='Graph', y='Edges',
                                       title='Edge Count Comparison',
                                       color='Edges', color_continuous_scale='Plasma')
                st.plotly_chart(fig_comp_edges, use_container_width=True)
            
            # Entity type comparison
            st.markdown("#### Entity Type Distribution Across Graphs")
            
            all_entity_types = set()
            entity_comparison = {}
            
            for graph_name in selected_graphs_compare:
                g_nodes, g_edges = load_graph_data(graph_name)
                g_stats = get_graph_statistics(g_nodes, g_edges)
                entity_comparison[graph_name] = dict(g_stats['node_types'])
                all_entity_types.update(g_stats['node_types'].keys())
            
            # Create comparison dataframe
            entity_comp_data = []
            for entity_type in all_entity_types:
                row = {'Entity Type': entity_type}
                for graph_name in selected_graphs_compare:
                    row[graph_name] = entity_comparison[graph_name].get(entity_type, 0)
                entity_comp_data.append(row)
            
            df_entity_comp = pd.DataFrame(entity_comp_data)
            
            # Stacked bar chart
            fig_entity = px.bar(df_entity_comp, x='Entity Type', 
                               y=selected_graphs_compare,
                               title='Entity Type Distribution (Stacked)',
                               barmode='group')
            fig_entity.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig_entity, use_container_width=True)

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: white; padding: 20px;">
    <p>🧠 <b>Knowledge Graph Dashboard v1.0</b></p>
    <p style="font-size: 12px;">
        ✓ Interactive Visualization • ✓ Advanced Search • ✓ NLP Query • ✓ Analytics • ✓ Multi-Graph Support • ✓ Export Tools
    </p>
    <p style="font-size: 11px; margin-top: 10px;">
        Built with Streamlit • FalkorDB • NetworkX • Plotly • PyVis
    </p>
</div>
""", unsafe_allow_html=True)



