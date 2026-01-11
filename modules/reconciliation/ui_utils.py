"""
UI Utilities Wrapper for Reconciliation Module.
Redirects to centralized common.ui_utils.
"""

import sys
import os

# Add project root to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import everything from centralized utils
from common.ui_utils import (
    apply_professional_style,
    get_download_filename,
    render_header,
    to_excel,
    download_report,
    display_dataframe
)
