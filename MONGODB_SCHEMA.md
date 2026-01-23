# MongoDB Schema Documentation

Comprehensive schema documentation for the IBI Reporting Application MongoDB database.

---

## Database Overview

| Property | Value |
|----------|-------|
| **Database Name** | `report_app` (configurable via `MONGO_DB_NAME`) |
| **Connection** | MongoDB Atlas (cloud) or local MongoDB |
| **Primary Use** | Store user data, report downloads, and module-specific reports |

---

## Collection Structure

### Module-Specific Collections

Each module has its own collection where reports are saved with tool identification:

| Collection | Module | Tools Count | Description |
|------------|--------|-------------|-------------|
| `amazon` | Amazon | 11 | Sales reports, OOS, P&L, RIS, etc. |
| `flipkart` | Flipkart | 5 | Sales reports, OOS, P&L, RIS, QWTT |
| `reconciliation` | Reconciliation | 12 | Brand-specific reconciliation tools |
| `leakagereconciliation` | Leakage Reconciliation | 6 | Leakage analysis tools |
| `stockmovement` | Stock Movement | 1 | Stock movement analysis |

### Centralized Registry

| Collection | Purpose |
|------------|---------|
| `report_registry` | **NEW** - Lightweight tracking of ALL reports across modules |
| `report_downloads` | Legacy download tracking (backward compatible) |
| `users` | User authentication |

---

## Collections

### 1. `report_registry` - Centralized Report Tracking (NEW)

Lightweight collection that tracks ALL reports across all modules. Use this for queries like "which reports were downloaded today" or "show all reports from amazon_sales_report tool".

#### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | MongoDB document ID |
| `module_name` | String | ✓ | Module: amazon, flipkart, reconciliation, etc. |
| `tool_name` | String | ✓ | Tool: amazon_sales_report, flipkart_oos, etc. |
| `report_name` | String | ✓ | Human-readable report name |
| `report_id` | String | - | Reference to full report in module collection |
| `generated_at` | Date | ✓ | When the report was generated |
| `generated_by` | String | ✓ | User who generated the report |
| `row_count` | Integer | - | Number of rows in the report |
| `filename` | String | - | Downloaded filename |
| `metadata` | Object | - | Additional metadata |

#### Sample Document

```json
{
    "_id": {"$oid": "678abc123..."},
    "module_name": "amazon",
    "tool_name": "amazon_sales_report",
    "report_name": "Amazon Sales Report",
    "report_id": "678def456...",
    "generated_at": {"$date": "2026-01-23T14:00:00.000Z"},
    "generated_by": "admin@test.com",
    "row_count": 1500,
    "filename": "amazon_sales_2026-01-23_14-00-00.xlsx",
    "metadata": {"date_range": "2026-01-01 to 2026-01-23"}
}
```

#### Indexes

```javascript
db.report_registry.createIndex({ "module_name": 1, "tool_name": 1 })
db.report_registry.createIndex({ "generated_at": -1 })
db.report_registry.createIndex({ "generated_by": 1 })
```

---

### 2. `users` - User Authentication

Stores user credentials and roles for application access.

#### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | MongoDB document ID |
| `email` | String | ✓ | User email (unique identifier) |
| `password` | Binary | ✓ | bcrypt hashed password |
| `role` | String | ✓ | User role: `admin`, `user`, `manager` |

#### Indexes

```javascript
db.users.createIndex({ "email": 1 }, { unique: true })
```

---

### 3. Module Collections (amazon, flipkart, reconciliation, etc.)

Each module has its own collection with reports saved by tool and name.

#### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | MongoDB document ID |
| `tool_name` | String | ✓ | **NEW**: Tool that generated the report |
| `report_name` | String | ✓ | Report name (e.g., "Amazon Sales Report") |
| `generated_at` | Date | ✓ | When report was generated |
| `generated_by` | String | ✓ | User who generated the report |
| `row_count` | Integer | ✓ | Number of rows in report |
| `column_count` | Integer | ✓ | Number of columns |
| `data` | Array | - | Report data (max 10,000 rows) |
| `metadata` | Object | - | Additional metadata |
| `downloads` | Array | ✓ | Array of download events |

#### Downloads Array Element

| Field | Type | Description |
|-------|------|-------------|
| `downloaded_at` | Date | When downloaded |
| `downloaded_by` | String | User who downloaded |
| `filename` | String | Downloaded filename with timestamp |

#### Sample Document

```json
{
    "_id": {"$oid": "678234abc..."},
    "tool_name": "amazon_sales_report",
    "report_name": "Amazon Sales Report",
    "generated_at": {"$date": "2026-01-23T16:30:00.000Z"},
    "generated_by": "admin@test.com",
    "row_count": 150,
    "column_count": 8,
    "data": [
        {"(Parent) ASIN": "B08XYZ123", "Brand": "Example", "Total Orders": 100},
        {"(Parent) ASIN": "B08XYZ456", "Brand": "Sample", "Total Orders": 200}
    ],
    "metadata": {
        "file_size_bytes": 24576,
        "date_range": "2026-01-01 to 2026-01-23"
    },
    "downloads": [
        {
            "downloaded_at": {"$date": "2026-01-23T16:31:00.000Z"},
            "downloaded_by": "admin@test.com",
            "filename": "amazon_sales_report_2026-01-23_16-31-00.xlsx"
        }
    ]
}
```

---

### 4. `report_downloads` - Central Report Log (Legacy)

Centralized log for all report downloads (backward compatible with existing code).

#### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | MongoDB document ID |
| `user_email` | String | ✓ | User who downloaded |
| `module` | String | ✓ | Module name |
| `report_name` | String | ✓ | Report name |
| `file_name` | String | ✓ | Downloaded filename |
| `downloaded_at` | Date | ✓ | Download timestamp |
| `metadata` | Object | - | Additional metadata |
| `report_data` | Array | - | Report data (max 10,000 rows) |

---

## Module-Tool Mapping

### Amazon Module (11 tools)

| Tool File | Tool Name | Description |
|-----------|-----------|-------------|
| `amazon_sales_report.py` | amazon_sales_report | Sales Report Analysis |
| `amazon_dailypl.py` | amazon_dailypl | Daily P&L Report |
| `amazon_dailypl_dyson.py` | amazon_dailypl_dyson | Dyson Daily P&L |
| `amazon_monthly_pl.py` | amazon_monthly_pl | Monthly P&L |
| `amazon_month_qtr_wise.py` | amazon_month_qtr_wise | Month/Quarter Analysis |
| `amazon_ris_new.py` | amazon_ris | RIS Report |
| `Amazon_OOS_New.py` | amazon_oos | OOS Report |
| `Amazon_PO_Working.py` | amazon_po | PO Working Report |
| `SalesvsReturn.py` | amazon_sales_vs_return | Sales vs Return Analysis |
| `amzon_qwtt_stock.py` | amazon_qwtt_stock | QWTT Stock Report |
| `OOS_Amazon_Daywise.py` | amazon_oos_daywise | OOS Daywise Report |

### Flipkart Module (5 tools)

| Tool File | Tool Name | Description |
|-----------|-----------|-------------|
| `flipkart_sales_report.py` | flipkart_sales_report | Sales Report |
| `flipkart_pl.py` | flipkart_pl | P&L Report |
| `Flipkart_OOS_New.py` | flipkart_oos | OOS Report |
| `Flipkart_RIS_New.py` | flipkart_ris | RIS Report |
| `Flipkart_QWTT_Stock.py` | flipkart_qwtt_stock | QWTT Stock Report |

### Reconciliation Module (12 tools)

| Tool File | Tool Name |
|-----------|-----------|
| `Dyson_Reconciliation.py` | dyson_reconciliation |
| `Nokia_Reconciliation.py` | nokia_reconciliation |
| `Bajaj_Reconciliation.py` | bajaj_reconciliation |
| `Crompton_Reconciliation.py` | crompton_reconciliation |
| `Glen_Reconciliation.py` | glen_reconciliation |
| `Hafele_Reconciliation.py` | hafele_reconciliation |
| `Panasonic_Reconciliation.py` | panasonic_reconciliation |
| `Sujata_Reconciliation.py` | sujata_reconciliation |
| `Tramontina_Reconciliation.py` | tramontina_reconciliation |
| `Trishna_Reconciliation.py` | trishna_reconciliation |
| `Usha_Reconciliation.py` | usha_reconciliation |
| `Wonderchef_Reconiliation.py` | wonderchef_reconciliation |

### Leakage Reconciliation Module (6 tools)

| Tool File | Tool Name |
|-----------|-----------|
| `Amazon_Pdf_Excel.py` | amazon_pdf_excel |
| `Amazon_ReturnReport_Analyzer.py` | amazon_return_analyzer |
| `Amazon_Support_Dyson.py` | amazon_support_dyson |
| `Refund_Cross_Check25.py` | refund_cross_check |
| `Replacement-without-Reimbursement.py` | replacement_wo_reimbursement |
| `Support_NCEMI.py` | support_ncemi |

### Stock Movement Module (1 tool)

| Tool File | Tool Name |
|-----------|-----------|
| `Stock_Movement_New.py` | stock_movement |

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                            │
│                     (Streamlit Tools)                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│           save_report_with_tracking() [NEW]                      │
│                 (common/mongo.py)                                │
│                                                                  │
│  • Saves full report to module collection                        │
│  • Registers in report_registry for tracking                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        MongoDB Atlas                             │
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ report_registry │  │     amazon      │  │    flipkart     │  │
│  │   (tracking)    │  │   (full data)   │  │   (full data)   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ reconciliation  │  │leakagereconcil. │  │  stockmovement  │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐                       │
│  │     users       │  │ report_downloads│ (legacy)              │
│  └─────────────────┘  └─────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Querying Examples

### Find all reports generated today

```javascript
db.report_registry.find({
    "generated_at": {
        "$gte": ISODate("2026-01-23T00:00:00Z"),
        "$lt": ISODate("2026-01-24T00:00:00Z")
    }
}).sort({ "generated_at": -1 })
```

### Find reports by module and tool

```javascript
db.report_registry.find({
    "module_name": "amazon",
    "tool_name": "amazon_sales_report"
}).sort({ "generated_at": -1 })
```

### Get all tools used by a specific user

```javascript
db.report_registry.aggregate([
    { "$match": { "generated_by": "admin@test.com" } },
    { "$group": {
        "_id": { "module": "$module_name", "tool": "$tool_name" },
        "count": { "$sum": 1 },
        "last_used": { "$max": "$generated_at" }
    }},
    { "$sort": { "count": -1 } }
])
```

### Get report statistics by module

```javascript
db.report_registry.aggregate([
    { "$group": {
        "_id": "$module_name",
        "total_reports": { "$sum": 1 },
        "total_rows": { "$sum": "$row_count" },
        "unique_tools": { "$addToSet": "$tool_name" }
    }},
    { "$project": {
        "module": "$_id",
        "total_reports": 1,
        "total_rows": 1,
        "tool_count": { "$size": "$unique_tools" }
    }}
])
```

### Find specific report by name in a module

```javascript
db.amazon.find({ "report_name": "Amazon Sales Report" })
    .sort({ "generated_at": -1 })
    .limit(1)
```

### Get download history for a report

```javascript
db.amazon.aggregate([
    { "$match": { "tool_name": "amazon_sales_report" } },
    { "$unwind": "$downloads" },
    { "$project": {
        "report_name": 1,
        "tool_name": 1,
        "downloaded_at": "$downloads.downloaded_at",
        "downloaded_by": "$downloads.downloaded_by",
        "filename": "$downloads.filename"
    }},
    { "$sort": { "downloaded_at": -1 } }
])
```

---

## Python Usage Examples

### Save a report with tracking

```python
from common.mongo import save_report_with_tracking

# Save report and register in central tracking
report_id = save_report_with_tracking(
    module_name="amazon",
    tool_name="amazon_sales_report",
    report_name="Amazon Sales Report",
    df_data=sales_df,
    user_email="user@example.com",
    filename="amazon_sales_2026-01-23.xlsx",
    metadata={"date_range": "Jan 2026"}
)
```

### Query the report registry

```python
from common.mongo import get_report_registry

# Get recent reports from amazon module
reports = get_report_registry(
    module_name="amazon",
    limit=50
)

# Get reports from a specific tool
tool_reports = get_report_registry(
    tool_name="amazon_sales_report",
    limit=20
)
```

### Use convenience wrappers

```python
from common.mongo_utils import save_report

# Simple save with tool name
save_report(
    module_name="amazon",
    report_name="Sales Analysis",
    data=df_data,
    tool_name="amazon_sales_report"
)
```

---

## Environment Configuration

```bash
# .env file
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGO_DB_NAME=report_app
```

---

## Size Limits & Constraints

| Constraint | Limit | Reason |
|------------|-------|--------|
| Max rows per document | 10,000 | MongoDB 16MB document limit |
| Max document size | 16 MB | MongoDB hard limit |
| Connection timeout | 10 seconds | Configured in mongo.py |
| Pool size | 10-50 connections | Configured in mongo.py |
