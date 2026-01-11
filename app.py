import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from auth.login import login
from common.layout import sidebar, get_module_icon, get_module_description

# Page configuration - must be first Streamlit command
st.set_page_config(
    page_title="IBI Reporting Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Apply premium CSS theme
css_path = os.path.join(os.path.dirname(__file__), "assets", "styles.css")
if os.path.exists(css_path):
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Authentication check
if "user" not in st.session_state:
    login()
    st.stop()

# Render sidebar with user info
sidebar(st.session_state["user"])

# Get all modules
MODULES_PATH = os.path.join(os.path.dirname(__file__), "modules")
modules = sorted([m for m in os.listdir(MODULES_PATH) if os.path.isdir(os.path.join(MODULES_PATH, m))])

# Module selection with icons
module_options = [f"{get_module_icon(m)} {m.title()}" for m in modules]
selected_option = st.sidebar.selectbox(
    "Select Module",
    module_options,
    label_visibility="collapsed"
)

# Extract actual module name
selected_module = modules[module_options.index(selected_option)]
module_path = os.path.join(MODULES_PATH, selected_module)

# Dashboard header with module info
st.markdown(f"""
    <div style="text-align: center; margin-bottom: 2rem;">
        <h1>{get_module_icon(selected_module)} {selected_module.upper()}</h1>
        <p style="color: #94a3b8; font-size: 1rem; margin-top: -1rem;">
            {get_module_description(selected_module)}
        </p>
    </div>
""", unsafe_allow_html=True)

# Quick stats bar (shows when user is logged in)
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown("""
        <div style="background: rgba(99, 102, 241, 0.1); border-radius: 12px; padding: 1rem; text-align: center; border: 1px solid rgba(99, 102, 241, 0.2);">
            <div style="font-size: 1.5rem;">👤</div>
            <div style="color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;">Logged In</div>
        </div>
    """, unsafe_allow_html=True)
with col2:
    report_count = len([f for f in os.listdir(module_path) if f.endswith('.py') and not f.startswith('__')])
    st.markdown(f"""
        <div style="background: rgba(34, 197, 94, 0.1); border-radius: 12px; padding: 1rem; text-align: center; border: 1px solid rgba(34, 197, 94, 0.2);">
            <div style="font-size: 1.5rem; color: #22c55e;">{report_count}</div>
            <div style="color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;">Reports Available</div>
        </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown("""
        <div style="background: rgba(168, 85, 247, 0.1); border-radius: 12px; padding: 1rem; text-align: center; border: 1px solid rgba(168, 85, 247, 0.2);">
            <div style="font-size: 1.5rem;">📁</div>
            <div style="color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;">Module Active</div>
        </div>
    """, unsafe_allow_html=True)
with col4:
    from datetime import datetime
    current_date = datetime.now().strftime("%b %d, %Y")
    st.markdown(f"""
        <div style="background: rgba(236, 72, 153, 0.1); border-radius: 12px; padding: 1rem; text-align: center; border: 1px solid rgba(236, 72, 153, 0.2);">
            <div style="font-size: 0.9rem; color: #f8fafc;">{current_date}</div>
            <div style="color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;">Today's Date</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Get all Python files in the module (excluding utils and __pycache__)
files = [
    f for f in os.listdir(module_path) 
    if f.endswith(".py") 
    and not f.startswith("__")
    and f not in ["mongo_utils.py", "ui_utils.py"]
]
files = sorted(files)

if not files:
    st.warning("No reports available in this module.")
    st.stop()

# Create clean tab names from filenames
tab_names = []
for f in files:
    name = f.replace(".py", "").replace("_", " ")
    # Capitalize each word
    name = " ".join(word.capitalize() for word in name.split())
    tab_names.append(name)

# Create tabs with styled names
tabs = st.tabs(tab_names)

import importlib.util

def load_module(file_path, module_dir):
    """Dynamically load and execute a Python module."""
    # Add module directory to path so local imports work
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    
    spec = importlib.util.spec_from_file_location("dynamic_module", file_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        st.error(f"Error loading module: {str(e)}")
    finally:
        # Clean up path to avoid conflicts
        if module_dir in sys.path:
            sys.path.remove(module_dir)

# Load each module file in its respective tab
for tab, file in zip(tabs, files):
    with tab:
        full_path = os.path.join(module_path, file)
        load_module(full_path, module_path)

# Footer
st.markdown("""
    <div style="text-align: center; margin-top: 3rem; padding: 1.5rem; border-top: 1px solid rgba(255,255,255,0.1);">
        <p style="color: #64748b; font-size: 0.8rem;">
            📊 IBI Reporting Dashboard • Built with ❤️ • © 2026
        </p>
    </div>
""", unsafe_allow_html=True)
