# Snaphire Developer Guide

This guide is intended for developers who wish to maintain, update, or extend the SnapHire application.

## 🏗️ Adding a New Tool

The application uses a dynamic discovery mechanism. To add a new Streamlit tool:

1. **Create the Python script**: Create your tool logic in a new `.py` file.
2. **Choose a Module**: Place the file in the appropriate subdirectory within `modules/` (e.g., `modules/amazon/my_new_tool.py`).
3. **Automatic Registration**: 
   - The Flask portal will automatically detect the new file and add it to the navigation menu.
   - The Streamlit dynamic loader (`streamlit_app.py`) will load it when called via `http://localhost:8501/?module=amazon&tool=my_new_tool.py`.

### 💡 Best Practices for Tools
- **Use Session State**: Streamlit reruns the whole script on every interaction. Use `st.session_state` to store processed data.
- **Cache Expensive Operations**: Use `@st.cache_data` for CSV parsing and heavy calculations.
- **Avoid Global Path Assumptions**: Use `os.path.dirname(__file__)` to reference local assets.

## 🔗 How Dynamic Loading Works

The magic happens in `streamlit_app.py` and the `app.py` file. They use `importlib.util` to import modules at runtime based on user selection.

```python
def load_module(file_path, module_dir):
    # Add module directory to path so local imports work
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    
    spec = importlib.util.spec_from_file_location("dynamic_module", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
```

## 🗄️ Database Integration

SnapHire uses MongoDB for persistence (logging reports, user auth, etc.).

- **Shared Utils**: Use `modules/reconciliation/mongo_utils.py` (if present) or common utility layers for database operations.
- **Schema**: Refer to `MONGODB_SCHEMA.md` in the root directory for detailed collection structures.

## 🎨 Styling

The application uses a custom "Professional/Premium" CSS theme.
- **Flask**: Styled via `flask_app/static/css/` (or embedded in templates).
- **Streamlit**: Overridden using `st.markdown("<style>...</style>", unsafe_allow_html=True)`. Global styles are often kept in `assets/styles.css`.

## 🧪 Testing

To test a new tool locally:
1. Start the Streamlit server directly:
   ```bash
   streamlit run streamlit_app.py -- --module=amazon --tool=my_new_tool.py
   ```
2. Or use the full launcher and navigate via the portal:
   ```bash
   python run.py
   ```
