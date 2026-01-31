import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import importlib.util

# Page configuration - must be first Streamlit command
st.set_page_config(
    page_title="IBI Tool",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Hide Streamlit UI elements when embedded (keep sidebar visible for file uploads)
st.markdown("""
<style>
    #MainMenu {visibility: visible; opacity: 0.1;}
    #MainMenu:hover {opacity: 1;}
    footer {visibility: hidden;}
    /* Force sidebar visibility and status toggle */
    section[data-testid="stSidebar"] {
        display: flex !important;
        visibility: visible !important;
    }
    [data-testid="collapsedControl"],
    button[data-testid="stSidebarCollapseButton"] {
        display: flex !important;
        position: fixed !important;
        top: 5px !important;
        left: 5px !important;
        z-index: 1000000 !important;
    }
    /* Keep sidebar visible for file uploaders */
    .block-container {
        padding-top: 1rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    /* Compact sidebar styling */
    [data-testid="stSidebar"] {
        min-width: 280px;
        max-width: 350px;
    }
</style>
""", unsafe_allow_html=True)

# Get URL parameters
query_params = st.query_params
module_name = query_params.get("module", None)
tool_name = query_params.get("tool", None)

MODULES_PATH = os.path.join(os.path.dirname(__file__), "modules")

def load_module(file_path, module_dir):
    """Dynamically load and execute a Python module."""
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    
    # Patch st.set_page_config to prevent "can only be called once" error
    original_set_page_config = st.set_page_config
    st.set_page_config = lambda *args, **kwargs: None
    
    spec = importlib.util.spec_from_file_location("dynamic_module", file_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        st.error(f"Error loading module: {str(e)}")
    finally:
        # Restore original function
        st.set_page_config = original_set_page_config
        if module_dir in sys.path:
            sys.path.remove(module_dir)

MODULE_DISPLAY_NAMES = {
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "reconciliation": "PO Reconciliation",
    "stockmovement": "Stock Movement",
    "leakagereconciliation": "Leakage Reconciliation",
    "system": "System Management",
}

def get_tool_display_name(filename):
    """Convert filename to display name."""
    name = filename.replace(".py", "").replace("_", " ")
    return " ".join(word.capitalize() for word in name.split())

def render_portal():
    """Render the main portal landing page."""
    st.title("📊 Snaphire Analytics Portal")
    st.markdown("---")
    
    # Get all modules
    modules = sorted([m for m in os.listdir(MODULES_PATH) 
                     if os.path.isdir(os.path.join(MODULES_PATH, m))])
    
    st.subheader("🗂️ Available Modules")
    
    cols = st.columns(3)
    for i, module in enumerate(modules):
        module_path = os.path.join(MODULES_PATH, module)
        tools = [f for f in os.listdir(module_path) 
                if f.endswith(".py") and not f.startswith("__") 
                and f not in ["mongo_utils.py", "ui_utils.py"]]
        
        display_name = MODULE_DISPLAY_NAMES.get(module.lower(), module.title())
        
        with cols[i % 3]:
            with st.expander(f"📁 **{display_name}** ({len(tools)} tools)", expanded=True):
                for tool in sorted(tools):
                    tool_display = get_tool_display_name(tool)
                    tool_url = f"?module={module}&tool={tool}"
                    st.markdown(f"🔧 [{tool_display}]({tool_url})")
    
    st.markdown("---")
    st.caption("Snaphire Analytics Portal | Built with Streamlit")

if module_name and tool_name:
    # Load the specific tool
    module_path = os.path.join(MODULES_PATH, module_name)
    full_path = os.path.join(module_path, tool_name)
    
    if os.path.exists(full_path):
        load_module(full_path, module_path)
    else:
        st.error(f"Tool not found: {tool_name}")
else:
    # Show portal landing page
    render_portal()

