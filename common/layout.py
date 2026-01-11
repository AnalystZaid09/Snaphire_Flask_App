"""
Layout Utilities for IBI Reporting Application.
Provides sidebar, module icons, and descriptions.
"""

import streamlit as st
from typing import Optional


# Module icons mapping
MODULE_ICONS = {
    "amazon": "🛒",
    "flipkart": "🛍️",
    "reconciliation": "📊",
    "leakagereconciliation": "🔍",
    "stockmovement": "📦"
}

# Module descriptions mapping
MODULE_DESCRIPTIONS = {
    "amazon": "Amazon sales, inventory, and reconciliation reports",
    "flipkart": "Flipkart sales, inventory, and reconciliation reports",
    "reconciliation": "Brand reconciliation and invoice matching",
    "leakagereconciliation": "Return analysis and leakage tracking",
    "stockmovement": "Stock movement and inventory tracking"
}


def get_module_icon(module_name: str) -> str:
    """Get the icon for a given module."""
    return MODULE_ICONS.get(module_name.lower(), "📁")


def get_module_description(module_name: str) -> str:
    """Get the description for a given module."""
    return MODULE_DESCRIPTIONS.get(module_name.lower(), "Module reports and analytics")


def sidebar(user: Optional[str] = None):
    """
    Render the sidebar with user info and navigation.
    
    Args:
        user: The logged-in user's email or identifier
    """
    with st.sidebar:
        # Logo/Brand
        st.markdown("""
            <div style="text-align: center; padding: 1rem 0; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 1rem;">
                <h2 style="margin: 0; color: #f8fafc;">📊 IBI Dashboard</h2>
                <p style="color: #94a3b8; font-size: 0.8rem; margin: 0.5rem 0 0 0;">Reporting & Analytics</p>
            </div>
        """, unsafe_allow_html=True)
        
        # User info
        if user:
            st.markdown(f"""
                <div style="background: rgba(99, 102, 241, 0.1); border-radius: 8px; padding: 0.75rem; margin-bottom: 1rem; border: 1px solid rgba(99, 102, 241, 0.2);">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-size: 1.2rem;">👤</span>
                        <div>
                            <div style="color: #f8fafc; font-size: 0.85rem; font-weight: 500;">{user}</div>
                            <div style="color: #94a3b8; font-size: 0.7rem;">Logged In</div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
        
        # Divider
        st.markdown("<hr style='border: none; border-top: 1px solid rgba(255,255,255,0.1); margin: 1rem 0;'>", unsafe_allow_html=True)
        
        # Module selection header
        st.markdown("""
            <p style="color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem;">
                📂 Select Module
            </p>
        """, unsafe_allow_html=True)
        
        # Logout button at bottom
        st.markdown("<div style='flex-grow: 1;'></div>", unsafe_allow_html=True)
        
        if st.button("🚪 Logout", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def render_module_header(module_name: str):
    """Render a styled header for the current module."""
    icon = get_module_icon(module_name)
    description = get_module_description(module_name)
    
    st.markdown(f"""
        <div style="text-align: center; margin-bottom: 2rem;">
            <h1 style="color: #f8fafc; font-size: 2rem; margin-bottom: 0.5rem;">
                {icon} {module_name.upper()}
            </h1>
            <p style="color: #94a3b8; font-size: 1rem;">
                {description}
            </p>
        </div>
    """, unsafe_allow_html=True)
