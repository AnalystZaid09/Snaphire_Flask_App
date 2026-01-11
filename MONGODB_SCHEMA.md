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

### Module-Specific Collections (NEW)

Each module has its own collection where reports are saved by name:

| Collection | Module | Reports |
|------------|--------|---------|
| `stock_movement` | Stock Movement | Amazon Business Pivot, Flipkart Business Pivot, Flipkart QWTT Inward, Amazon QWTT Inward |
| `amazon` | Amazon | Brand Manager Analysis, Brand Analysis, etc. |
| `flipkart` | Flipkart | Sales Reports, OOS Reports |
| `reconciliation` | Reconciliation | Brand-specific reconciliation reports |

---

## Collections

### 1. `users` - User Authentication

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

### 2. Module Collections (e.g., `stock_movement`, `amazon`, `flipkart`)

Each module has its own collection with reports saved by name.

#### Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_id` | ObjectId | Auto | MongoDB document ID |
| `report_name` | String | ✓ | Report name (e.g., "Amazon Business Pivot") |
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
    "report_name": "Amazon Business Pivot",
    "generated_at": {"$date": "2026-01-11T16:30:00.000Z"},
    "generated_by": "admin@test.com",
    "row_count": 150,
    "column_count": 8,
    "data": [
        {"(Parent) ASIN": "B08XYZ123", "Brand": "Example", "Total Orders": 100},
        {"(Parent) ASIN": "B08XYZ456", "Brand": "Sample", "Total Orders": 200}
    ],
    "metadata": {
        "file_size_bytes": 24576
    },
    "downloads": [
        {
            "downloaded_at": {"$date": "2026-01-11T16:31:00.000Z"},
            "downloaded_by": "admin@test.com",
            "filename": "amazon_business_pivot_2026-01-11_16-31-00.xlsx"
        },
        {
            "downloaded_at": {"$date": "2026-01-11T17:00:00.000Z"},
            "downloaded_by": "user@test.com",
            "filename": "amazon_business_pivot_2026-01-11_17-00-00.xlsx"
        }
    ]
}
```

---

### 3. `report_downloads` - Central Report Log (Legacy)

Centralized log for all report downloads (backward compatible).

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

#### Indexes

```javascript
db.report_downloads.createIndex({ "user_email": 1, "downloaded_at": -1 })
db.report_downloads.createIndex({ "module": 1 })
db.report_downloads.createIndex({ "downloaded_at": -1 })
```

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
│               download_module_report()                           │
│                 (common/ui_utils.py)                             │
│                                                                  │
│  • Creates download button                                       │
│  • On click: saves to module collection + logs download         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│               save_and_track_report()                            │
│                   (common/mongo.py)                              │
│                                                                  │
│  1. save_module_report() → Insert to module collection          │
│  2. log_download_event() → Add to downloads array               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        MongoDB Atlas                             │
│                                                                  │
│  ┌─────────────┐ ┌──────────────────┐ ┌───────────────────┐    │
│  │   users     │ │ stock_movement   │ │     amazon        │    │
│  └─────────────┘ └──────────────────┘ └───────────────────┘    │
│                                                                  │
│  ┌─────────────┐ ┌──────────────────┐ ┌───────────────────┐    │
│  │  flipkart   │ │ reconciliation   │ │ report_downloads  │    │
│  └─────────────┘ └──────────────────┘ └───────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stock Movement Collection Example

The `stock_movement` collection stores 4 reports:

| Report Name | Description |
|-------------|-------------|
| `Amazon Business Pivot` | Amazon business data with PM enrichment |
| `Flipkart Business Pivot` | Flipkart business data with PM enrichment |
| `Flipkart QWTT Inward` | Flipkart inward requirements |
| `Amazon QWTT Inward` | Amazon inward requirements |

Each report document includes:
- Report data (limited to 10K rows)
- Generation timestamp and user
- Download history with timestamps

---

## Querying Examples

### Find all reports in a module

```javascript
db.stock_movement.find({})
    .sort({ "generated_at": -1 })
```

### Find specific report by name

```javascript
db.stock_movement.find({ "report_name": "Amazon Business Pivot" })
    .sort({ "generated_at": -1 })
    .limit(1)
```

### Get download history for a report

```javascript
db.stock_movement.aggregate([
    { "$match": { "report_name": "Amazon Business Pivot" } },
    { "$unwind": "$downloads" },
    { "$project": {
        "report_name": 1,
        "downloaded_at": "$downloads.downloaded_at",
        "downloaded_by": "$downloads.downloaded_by",
        "filename": "$downloads.filename"
    }},
    { "$sort": { "downloaded_at": -1 } }
])
```

### Get report statistics by module

```javascript
db.stock_movement.aggregate([
    { "$group": {
        "_id": "$report_name",
        "count": { "$sum": 1 },
        "total_downloads": { "$sum": { "$size": "$downloads" } },
        "last_generated": { "$max": "$generated_at" }
    }}
])
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
