# Snaphire Module Guide

This guide describes the various modules and tools available in the Snaphire application, categorized by their primary business function.

## 📦 Amazon Module
The Amazon module focus on sales, inventory, and profitability analysis for Amazon Seller Central data.

- **Sales vs Return**: Analyzes the ratio of sales to returns over a specific period.
- **Amazon OOS (Out of Stock)**: Identifies products that are out of stock or at risk of going out of stock.
- **Amazon PO Working**: A dual-role analysis tool (Portal/Manager) that calculates Daily Run Rate (DRR) and Days of Coverage (DOC). It identifies low stock items (DOC ≤ 7) and performs Regional Inventory Storage (RIS) analysis to optimize stock distribution across Fulfillment Centers.
- **Amazon RIS New**: Latest Regional Inventory Storage (RIS) dashboard featuring dual-mode processing (Portal/Manager). Provides in-depth analysis of stock distribution across clusters, states, and brands with automatic normalization of shipping data.
- **P&L Analysis**: Daily, Monthly, and Quarterly Profit & Loss statements tailored for Amazon's fee structure.
- **Sales Report**: General sales performance tracking.

## 🛍️ Flipkart Module
Equivalent tools for Flipkart seller data.

- **Flipkart OOS**: Out-of-stock analysis for Flipkart.
- **Flipkart P&L**: Profit calculations specifically for Flipkart's marketplace.
- **Flipkart Sales Report**: Comprehensive sales metrics for Flipkart.

## ⚖️ Reconciliation & Leakage
Advanced tools for financial auditing and discrepancy detection.

### Reconciliation
Brand-specific reconciliation logic for various partners:
- Bajaj, Crompton, Dyson, Hafele, Nokia, Panasonic, Sujata, Usha, Wonderchef, etc.
- These tools reconcile internal records with marketplace reports to ensure payment accuracy.

### Leakage Reconciliation
Tools to find "leaking" revenue or missed refunds:
- **Refund Cross Check**: Ensures all refunds are accounted for.
- **Replacement without Reimbursement**: Finds cases where items were replaced but the seller was never reimbursed for the loss.
- **Amazon Return Report Analyzer**: Deep dive into return reasons and status.

## ⚙️ System & Utilities
- **Database Management**: Schema updates and maintenance.
- **Stock Movement**: Tracking inventory transfers between locations.

---

> [!TIP]
> Each tool is designed to accept CSV or Excel exports from the respective marketplace seller portals. Ensure column headers match the expected format (refer to tool help sections within the app).
