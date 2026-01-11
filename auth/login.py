import streamlit as st
from auth.auth_utils import authenticate_user

def login():
    """Clean, professional login page with contained card layout."""
    
    # Hide Streamlit header and footer for clean login
    st.markdown("""
        <style>
        /* Hide Streamlit branding */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        
        /* Dark background */
        .stApp {
            background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
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
        
        /* Login card container */
        .login-card {
            max-width: 400px;
            margin: 2rem auto;
            background: rgba(30, 30, 50, 0.95);
            border-radius: 20px;
            padding: 2.5rem;
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }
        
        /* Logo area */
        .login-logo {
            text-align: center;
            margin-bottom: 1.5rem;
        }
        
        .login-logo-icon {
            width: 70px;
            height: 70px;
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
            border-radius: 16px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 2rem;
            margin-bottom: 1rem;
            box-shadow: 0 8px 25px rgba(99, 102, 241, 0.4);
        }
        
        .login-title {
            font-size: 1.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0;
        }
        
        .login-subtitle {
            color: #94a3b8;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }
        
        /* Form styling */
        .login-card .stTextInput > label {
            color: #94a3b8 !important;
            font-size: 0.85rem !important;
            font-weight: 500 !important;
        }
        
        .login-card .stTextInput > div > div > input {
            background: rgba(255, 255, 255, 0.08) !important;
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            border-radius: 10px !important;
            color: #f8fafc !important;
            padding: 0.8rem 1rem !important;
        }
        
        .login-card .stTextInput > div > div > input:focus {
            border-color: #6366f1 !important;
            box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2) !important;
        }
        
        .login-card .stButton > button {
            width: 100%;
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%) !important;
            border: none !important;
            border-radius: 10px !important;
            padding: 0.8rem !important;
            font-weight: 600 !important;
            font-size: 1rem !important;
            margin-top: 0.5rem;
            box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
        }
        
        .login-card .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
        }
        
        /* Footer */
        .login-footer {
            text-align: center;
            margin-top: 1.5rem;
            padding-top: 1rem;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            color: #64748b;
            font-size: 0.75rem;
        }
        
        /* Alerts inside card */
        .login-card .stAlert {
            margin-top: 1rem;
            border-radius: 8px;
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
        
        if st.button("🚀 Sign In", key="login_btn", use_container_width=True):
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
