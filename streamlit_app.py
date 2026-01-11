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
    initial_sidebar_state="collapsed"
)

# Hide Streamlit UI elements when embedded
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    /* Sidebar kept visible for file uploaders in modules */
    .block-container {
        padding-top: 1rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
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
    
    spec = importlib.util.spec_from_file_location("dynamic_module", file_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        st.error(f"Error loading module: {str(e)}")
    finally:
        if module_dir in sys.path:
            sys.path.remove(module_dir)

if module_name and tool_name:
    # Load the specific tool
    module_path = os.path.join(MODULES_PATH, module_name)
    full_path = os.path.join(module_path, tool_name)
    
    if os.path.exists(full_path):
        load_module(full_path, module_path)
    else:
        st.error(f"Tool not found: {tool_name}")
else:
    # Show default message
    st.info("Select a tool from the portal to get started.")

