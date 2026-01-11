from flask import Flask, render_template, redirect, url_for, session, request
from functools import wraps
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Module configuration
MODULES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "modules")

MODULE_DISPLAY_NAMES = {
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "reconciliation": "PO Reconciliation",
    "stockmovement": "Stock Movement",
    "leakagereconciliation": "Leakage Reconciliation",
}

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_modules():
    """Get all available modules."""
    modules = sorted([m for m in os.listdir(MODULES_PATH) 
                     if os.path.isdir(os.path.join(MODULES_PATH, m))])
    return modules

def get_module_display_name(folder_name):
    """Get display name for a module."""
    return MODULE_DISPLAY_NAMES.get(folder_name.lower(), folder_name.title())

def get_tool_count(module_name):
    """Get the number of tools in a module."""
    module_path = os.path.join(MODULES_PATH, module_name)
    files = [f for f in os.listdir(module_path) 
             if f.endswith(".py") 
             and not f.startswith("__")
             and f not in ["mongo_utils.py", "ui_utils.py"]]
    return len(files)

def get_tools(module_name):
    """Get list of tools in a module."""
    module_path = os.path.join(MODULES_PATH, module_name)
    files = [f for f in os.listdir(module_path) 
             if f.endswith(".py") 
             and not f.startswith("__")
             and f not in ["mongo_utils.py", "ui_utils.py"]]
    return sorted(files)

def get_tool_display_name(filename):
    """Convert filename to display name."""
    name = filename.replace(".py", "").replace("_", " ")
    return " ".join(word.capitalize() for word in name.split())

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if 'user' in session:
        return redirect(url_for('home'))
    
    error = None
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            from auth.auth_utils import authenticate_user
            user = authenticate_user(email, password)
            if user:
                session['user'] = user['email']
                return redirect(url_for('home'))
            else:
                error = "Invalid email or password"
        except Exception as e:
            error = f"Authentication error: {str(e)}"
    
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    """Logout and redirect to login page."""
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    """Home page with module cards."""
    modules = get_modules()
    module_data = []
    for m in modules:
        module_data.append({
            'name': m,
            'display_name': get_module_display_name(m),
            'tool_count': get_tool_count(m)
        })
    return render_template('home.html', modules=module_data, user=session.get('user'))

@app.route('/module/<module_name>')
@login_required
def module_page(module_name):
    """Module page with tool cards."""
    modules = get_modules()
    if module_name not in modules:
        return redirect(url_for('home'))
    
    tools = get_tools(module_name)
    tool_data = []
    for t in tools:
        tool_data.append({
            'filename': t,
            'display_name': get_tool_display_name(t)
        })
    
    # Module list for sidebar
    module_list = []
    for m in modules:
        module_list.append({
            'name': m,
            'display_name': get_module_display_name(m),
            'active': m == module_name
        })
    
    return render_template('module.html', 
                         module_name=module_name,
                         module_display=get_module_display_name(module_name),
                         tools=tool_data,
                         modules=module_list,
                         user=session.get('user'))

@app.route('/tool/<module_name>/<tool_name>')
@login_required
def tool_page(module_name, tool_name):
    """Tool page with embedded Streamlit."""
    modules = get_modules()
    if module_name not in modules:
        return redirect(url_for('home'))
    
    tools = get_tools(module_name)
    if tool_name not in tools:
        return redirect(url_for('module_page', module_name=module_name))
    
    # Module list for sidebar
    module_list = []
    for m in modules:
        module_list.append({
            'name': m,
            'display_name': get_module_display_name(m),
            'active': m == module_name
        })
    
    # Streamlit URL from environment variable or default to localhost
    base_url = os.getenv("STREAMLIT_URL", "http://localhost:8501")
    streamlit_url = f"{base_url}/?module={module_name}&tool={tool_name}"
    
    return render_template('tool.html',
                         module_name=module_name,
                         module_display=get_module_display_name(module_name),
                         tool_name=tool_name,
                         tool_display=get_tool_display_name(tool_name),
                         streamlit_url=streamlit_url,
                         modules=module_list,
                         user=session.get('user'))

@app.route('/debug-env')
def debug_env():
    """Diagnostic route to check environment variables on Vercel."""
    import os
    # We mask the sensitive part of the URI for security
    uri = os.getenv("MONGO_URI", "Not Found")
    masked_uri = "Found" if uri != "Not Found" else "Not Found"
    
    return {
        "VERCEL": os.getenv("VERCEL", "Not Found"),
        "MONGO_URI_STATUS": masked_uri,
        "MONGO_DB_NAME": os.getenv("MONGO_DB_NAME", "Not Found"),
        "STREAMLIT_URL": os.getenv("STREAMLIT_URL", "Not Found"),
        "MODULES_PATH_EXISTS": os.path.exists(MODULES_PATH),
        "PWD": os.getcwd()
    }

if __name__ == '__main__':
    app.run(debug=True, port=5000)

