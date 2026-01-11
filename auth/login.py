import streamlit as st
from auth.auth_utils import authenticate_user

def login():
    """Clean, minimal login page with light theme."""
    
    # Hide Streamlit header and footer for clean login
    st.markdown("""
        <style>
        /* Hide Streamlit branding */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* Light background with subtle gradient */
        .stApp {
            background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        }
        
        /* Remove default padding */
        .block-container {
            padding-top: 3rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            max-width: 100% !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        
        /* Login card container - Minimal White Card */
        .login-card {
            max-width: 420px;
            margin: 3rem auto;
            background: #ffffff;
            border-radius: 16px;
            padding: 2.5rem;
            border: 1px solid #e2e8f0;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
        }
        
        /* Logo area */
        .login-logo {
            text-align: center;
            margin-bottom: 2rem;
        }
        
        .login-logo-icon {
            width: 64px;
            height: 64px;
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
            border-radius: 14px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 1.8rem;
            margin-bottom: 1rem;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
        }
        
        .login-title {
            font-size: 1.5rem;
            font-weight: 700;
            color: #1e293b;
            margin: 0;
        }
        
        .login-subtitle {
            color: #64748b;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }
        
        /* Form styling */
        .login-card .stTextInput > label {
            color: #475569 !important;
            font-size: 0.85rem !important;
            font-weight: 500 !important;
        }
        
        .login-card .stTextInput > div > div > input {
            background: #f8fafc !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 10px !important;
            color: #1e293b !important;
            padding: 0.8rem 1rem !important;
            font-size: 0.95rem !important;
        }
        
        .login-card .stTextInput > div > div > input::placeholder {
            color: #94a3b8 !important;
        }
        
        .login-card .stTextInput > div > div > input:focus {
            border-color: #3b82f6 !important;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15) !important;
        }
        
        .login-card .stButton > button {
            width: 100%;
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
            border: none !important;
            border-radius: 10px !important;
            padding: 0.85rem !important;
            font-weight: 600 !important;
            font-size: 1rem !important;
            margin-top: 0.75rem;
            color: white !important;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
            transition: all 0.2s ease;
        }
        
        .login-card .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4);
        }
        
        /* Footer */
        .login-footer {
            text-align: center;
            margin-top: 1.5rem;
            padding-top: 1.25rem;
            border-top: 1px solid #e2e8f0;
            color: #94a3b8;
            font-size: 0.8rem;
        }
        
        /* Alerts inside card */
        .login-card .stAlert {
            margin-top: 1rem;
            border-radius: 8px;
        }
        
        /* Success message styling */
        .login-card .stSuccess {
            background: #f0fdf4 !important;
            border-color: #86efac !important;
        }
        
        /* Error message styling */
        .login-card .stError {
            background: #fef2f2 !important;
            border-color: #fecaca !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # Centered login card using columns
    col1, col2, col3 = st.columns([1, 1.2, 1])
    
    with col2:
        # Start login card container
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        
        # Logo and branding
        st.markdown('''
            <div class="login-logo">
                <div class="login-logo-icon">📊</div>
                <h1 class="login-title">IBI Reporting</h1>
                <p class="login-subtitle">Sign in to access your dashboard</p>
            </div>
        ''', unsafe_allow_html=True)
        
        # Login form
        email = st.text_input("Email Address", placeholder="Enter your email", key="login_email")
        password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")
        
        if st.button("Sign In", key="login_btn", use_container_width=True):
            if not email or not password:
                st.error("⚠️ Please enter both email and password")
            else:
                with st.spinner("Authenticating..."):
                    user = authenticate_user(email, password)
                    if user:
                        st.session_state["user"] = user["email"]
                        st.success("✅ Login successful!")
                        st.rerun()
                    else:
                        st.error("❌ Invalid email or password")
        
        # Footer
        st.markdown('''
            <div class="login-footer">
                🔐 Secure Login • © 2026 IBI Reporting
            </div>
        ''', unsafe_allow_html=True)
        
        # Close login card container
        st.markdown('</div>', unsafe_allow_html=True)
