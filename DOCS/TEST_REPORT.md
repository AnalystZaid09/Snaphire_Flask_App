# Snaphire: Functional Specification & Test Report
**Version**: 1.0 | **Role**: Software Quality Assurance

---

## 🔬 Testing Overview
This report provides a functional breakdown and verification of the tools within the Snaphire platform. Each tool has been examined for data handling integrity, input validation, and output reliability.

---

## 📦 Amazon Module

### 1. Sales vs Return Data Analyzer
- **Functionality**: Performs a multi-file analysis to calculate return percentages by Brand and ASIN.
- **Inputs**: 
    - B2B/B2C ZIP files (Marketplace reports)
    - Seller Flex CSV (Return data)
    - FBA Return CSV
    - Purchase Master Excel (Product details)
- **Key Logic**: 
    - Normalizes headers from multiple sources.
    - Filters for 'Shipment' transaction types only.
    - Calculates the "Return In %" metric [(Total Return / Quantity) * 100].
- **Test Findings**:
    - ✅ Handles large datasets by streaming to disk (RAM-safe).
    - ✅ Automatic grand total calculation for summaries.
    - ✅ Dynamic handling of 'Disposition' statuses from FBA reports.

### 2. Amazon PO Working (OOS Analysis)
- **Functionality**: Predicts stockouts and regional inventory imbalances.
- **Roles**: Supports both **Portal** (Standard) and **Manager** (Enhanced RIS) perspectives.
- **Inputs**: 
    - Business Report CSV (Sales)
    - Inventory CSV (Stock levels)
    - RIS Data (Regional storage)
    - PM Excel (Product metadata)
- **Key Logic**: 
    - Calculates Daily Run Rate (DRR) and Days of Coverage (DOC).
    - Highlights critical items (DOC = 0) and low-stock alerts (DOC ≤ 7).
    - Maps stock distribution across high/low RIS clusters and states.
- **Verification**:
    - ✅ Accurate join logic between Business, Inventory, and RIS data.
    - ✅ Dynamic role-based file requirements.
    - ✅ Automatic grand-summary metrics for rapid decision making.

---

## 🛍️ Flipkart Module

### 1. Flipkart P&L Analysis
- **Functionality**: A comprehensive profit and loss analyzer for Flipkart transactions.
- **Inputs**: 
    - Payment File (Orders sheet)
    - Uni Orders (Reference)
    - FSN Master
    - Flipkart PM (Product Master)
- **Key Logic**: 
    - Filters out refunded and "protection fund" orders to isolate net sales.
    - Matches FSN/Seller SKU to Product Master for cost attribution.
    - Deducts a 3% turnover fee to calculate "After 3% Profit."
- **Test Findings**:
    - ✅ Advanced data styling: High-contrast color coding in Excel exports (Profit = Green, Loss = Red).
    - ✅ High-precision metrics: Real-time calculation of net margins across diverse brands.

---

## ⚖️ Reconciliation & Leakage

### 1. Brand Reconciliation (e.g., Bajaj, Hafele)
- **Functionality**: PDF-to-Excel matching using OCR.
- **Verification**: Successfully isolates price and quantity mismatches at the line-item level.

### 2. Refund Cross-Check (Leakage Module)
- **Functionality**: Identifies missing reimbursements by cross-referencing multiple data streams.
- **Inputs**: Refund data, QWT Shipments, FBA/Seller Flex Returns, Safe-T Claims, and Reimbursement reports.
- **Key Logic**: 
    - Performs complex left-joins across 6 disparate data sources using Order ID as the primary key.
    - Applies dynamic TAT (Turnaround Time) filters to identify aged unreimbursed returns.
- **Test Findings**:
    - ✅ Discrepancy Detection: Effectively identifies orders that were refunded but never returned or reimbursed.
    - ✅ Dynamic TAT Filtering: Allows users to tune analysis based on business cycles (e.g., 50-75 days).

---

## ⚙️ System & Utilities

### 1. Report History
- **Functionality**: Centralized logging of all analytical activities.
- **Verification**: Every report generation and download event is timestamped and saved to MongoDB for audit trails.

### 2. Stock Movement
- **Functionality**: Tracks inventory flow between warehouse locations and marketplace fulfillment centers.

---

## 🛡️ Global Functional Checks

| **Feature** | **Status** | **Quality Note** |
| :--- | :--- | :--- |
| **Header Normalization** | ✅ Passed | Tools use `.title().strip()` to handle inconsistent file headers. |
| **Download Reliability** | ✅ Passed | All tools provide both Excel and CSV formats with timestamped filenames. |
| **Error Handling** | ✅ Passed | Uses `try-except` blocks with `st.error` and `traceback` for visibility. |
| **Database Sync** | ✅ Passed | Logs successful report generation to MongoDB. |

---
*Verified by AI Testing Agent (Antigravity)*
