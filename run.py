"""
IBI Ops Super App - Tools Portal Launcher

Run this script to start the application:
    python run.py

This will start both Flask (portal) and Streamlit (tools) servers.
Access the portal at: http://localhost:5000
"""

import subprocess
import sys
import time
import webbrowser
import os
from threading import Thread

def start_streamlit():
    """Start the Streamlit server in background."""
    streamlit_path = os.path.join(os.path.dirname(__file__), "streamlit_app.py")
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", streamlit_path, 
         "--server.port=8501", 
         "--server.headless=true",
         "--server.enableXsrfProtection=false",
         "--server.enableCORS=false",
         "--server.maxUploadSize=2000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def start_flask():
    """Start the Flask server."""
    # Import and run Flask app
    from flask_app.routes import app
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

def open_browser():
    """Open browser after a short delay."""
    time.sleep(2)
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    print("=" * 50)
    print("  IBI Ops Super App — Tools Portal")
    print("=" * 50)
    print()
    print("Starting servers...")
    print()
    
    # Start Streamlit in background
    print("[1/2] Starting Streamlit server on port 8501...")
    streamlit_thread = Thread(target=start_streamlit, daemon=True)
    streamlit_thread.start()
    
    # Open browser
    print("[2/2] Starting Flask portal on port 5000...")
    browser_thread = Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    print()
    print("Portal URL: http://localhost:5000")
    print()
    print("Press Ctrl+C to stop the servers")
    print("-" * 50)
    
    # Start Flask (blocking)
    try:
        start_flask()
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)
