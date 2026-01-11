# Flask Code App - Snaphire Analytics Platform

A comprehensive business analytics and reconciliation platform for Amazon and Flipkart e-commerce operations.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+** - [Download](https://www.python.org/downloads/)
- **MongoDB Atlas Account** - [Sign Up Free](https://www.mongodb.com/cloud/atlas/register)
- **Azure Document Intelligence** (optional, for PDF reconciliation) - [Azure Portal](https://portal.azure.com/)

---

## 📦 Installation

### 1. Extract the Application
Extract `Flask_Code_App.zip` to your desired folder.

### 2. Open Terminal
```bash
cd path/to/Flask_Code_App
```

### 3. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment
Copy `.env.example` to `.env` and fill in your credentials:

```env
# MongoDB Connection (Required)
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/dbname?retryWrites=true&w=majority
MONGO_DB_NAME=snaphire_db

# Azure Document Intelligence (Required for Reconciliation tools)
AZURE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_KEY=your-azure-key
```

### 6. Create Admin User
```bash
python create_admin.py
```
Default credentials: `admin` / `admin123`

### 7. Run the Application
```bash
python run.py
```

### 8. Access the Portal
Open your browser: **http://localhost:5000**

---

## 📁 Project Structure

```
Flask_Code_App/
├── flask_app/              # Flask portal (main UI)
├── modules/
│   ├── amazon/             # Amazon analytics tools
│   ├── flipkart/           # Flipkart analytics tools
│   ├── reconciliation/     # Brand reconciliation tools
│   ├── leakagereconciliation/  # Leakage analysis tools
│   └── stockmovement/      # Stock management tools
├── common/                 # Shared utilities
├── auth/                   # Authentication system
├── .env                    # Environment variables (create this)
├── requirements.txt        # Python dependencies
└── run.py                  # Application launcher
```

---

## 🔧 Features

### Amazon Module
- Sales Report Analysis
- RIS (Retail Inventory System) Reports
- QWTT Stock Management
- OOS (Out of Stock) Analysis
- Daily/Monthly P&L Reports

### Flipkart Module
- Sales Report Analysis
- RIS Reports
- QWTT Stock Management
- OOS Analysis

### Reconciliation Module
- Bajaj, Crompton, Dyson, Glen, Hafele
- Nokia, Panasonic, Sujata, Tramontina, Usha
- PDF Invoice vs Excel PO matching

### Leakage Reconciliation
- Return Report Analysis
- Refund Cross-Check
- Sales vs Return Analysis
- NCEMI Support Analysis

---

## 🗄️ MongoDB Setup

### Option A: MongoDB Atlas (Recommended)

1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a free cluster
3. Create a database user
4. Whitelist your IP (or use 0.0.0.0/0 for any IP)
5. Get your connection string:
   - Click "Connect" → "Connect your application"
   - Copy the URI and replace `<password>` with your password

### Option B: Local MongoDB

1. Install [MongoDB Community Server](https://www.mongodb.com/try/download/community)
2. Start MongoDB service
3. Use connection string: `mongodb://localhost:27017/snaphire_db`

---

## ☁️ Cloud Deployment

### 🏆 Option A: Railway.app (Unified Deployment - Recommended)
Railway is the most optimal platform as it runs both the Flask Portal and Streamlit Tools under one single link.

1.  Push code to GitHub.
2.  Connect repository in Railway.
3.  Add all environment variables (`MONGO_URI`, `MONGO_DB_NAME`, etc.).
4.  **Railway will automatically use the `Procfile` and `run.py` to start everything.**

### ☁️ Option B: Vercel (Split Deployment)
If you prefer Vercel for the frontend, note that it cannot run Streamlit. You must use a "Split Deployment":

1.  **Deploy Portal to Vercel**: Connect GitHub to Vercel.
2.  **Deploy Tools elsewhere**: Host the same repo on **Streamlit Cloud** or **Railway**.
3.  **Link them**: Add the variable **`STREAMLIT_URL`** to your Vercel project settings, pointing to your tools host (e.g., `https://my-tools.streamlit.app`).

---

## 🔐 Security Notes

- Never commit `.env` file to version control
- Change default admin password after first login
- Use strong MongoDB passwords with URL encoding for special characters
- Restrict MongoDB IP whitelist in production

---

## 📞 Support

For technical support or issues, contact your system administrator.

---

## 📄 License

Proprietary - All rights reserved.
