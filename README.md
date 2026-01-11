# IBI Ops Super App — Tools Portal

A unified dashboard for operations tools, combining a Flask-based portal with embedded Streamlit analytical tools.

## Features
- **Unified Portal**: Centralized access to all operations modules.
- **Embedded Tools**: Streamlit apps for Amazon, Flipkart, Stock Movement, and Reconciliation.
- **Centralized MongoDB Logging**: Automatic tracking of every report generation and download.
- **Professional Analytics**: Pivot tables, trend analysis, and automated cross-checks.

## Architecture
- **Flask**: Serves the portal UI and handles authentication.
- **Streamlit**: Powers the analytical tools.
- **MongoDB**: Stores user data and report download history.

## Local Setup
1. Clone the repository:
   ```bash
   git clone <your-repo-url>
   cd streamlit_code
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables in a `.env` file:
   ```
   MONGO_URI="your_mongodb_uri"
   MONGO_DB_NAME="report_app"
   ```
4. Run the application:
   ```bash
   python run.py
   ```
   The portal will be available at `http://localhost:5000`.

## Deployment
This project is configured for deployment to **Vercel** (Flask Portal) and **Streamlit Cloud** (Analytical Tools).
Refer to `walkthrough.md` for detailed deployment instructions.
