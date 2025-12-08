# Cash Flow Early Warning System: A Data-Driven Approach

## Executive Summary

To improve the accuracy of our cash flow forecasting model, we analyzed the historical financial data of subsidiaries with a 'High' `cash_flow_risk_level`. This report details the findings from our analysis of key financial indicators in the six months preceding a cash flow crisis. By comparing high-risk subsidiaries to their financially healthy counterparts, we have identified a set of leading indicators and thresholds that can provide a 2-3 month early warning for potential cash flow issues.

## Analysis and Findings

Our analysis focused on three key areas: revenue recognition, accounts receivable (AR) management, and expense control. The data reveals significant differences in the behavior of high-risk versus healthy subsidiaries in the months leading up to a crisis.

![Financial Indicators Comparison](financial_indicators_comparison.png)

### Key Observations:

1.  **Accounts Receivable Mismanagement is a Major Red Flag:**
    *   **Weighted Average Days Outstanding (WADO):** High-risk subsidiaries spent a significantly larger proportion of the pre-crisis period with a WADO of over 45 days. This indicates a systemic issue with collecting payments.
    *   **Consecutive Rise in Overdue Percentage:** The analysis showed that high-risk subsidiaries were far more likely to experience a continuous increase in their overdue receivables for three or more consecutive months. This sustained trend is a strong signal of deteriorating AR health.

2.  **Revenue Volatility as a Precursor to Crisis:**
    *   High-risk subsidiaries exhibited much greater volatility in their monthly revenues, with a higher frequency of fluctuations exceeding 20%. This instability in income is a significant stressor on cash flow planning.

3.  **Expense Growth Outpacing Revenue Growth:**
    *   A critical finding is the divergence between expense and revenue growth rates. In high-risk subsidiaries, expense growth consistently outpaced revenue growth, indicating poor cost control and an unsustainable operational model. This divergence puts a direct strain on cash reserves.

## Actionable Insights and Recommendations

Based on these findings, we recommend the implementation of an automated monitoring system that tracks the following indicators for all subsidiaries:

1.  **Threshold for WADO:**
    *   **Recommendation:** Flag any subsidiary where the `weighted_average_days_outstanding` exceeds **45 days** for more than **two consecutive months**. This provides an early signal of collection inefficiencies.

2.  **Monitoring Overdue Percentages:**
    *   **Recommendation:** Trigger an alert when a subsidiary's `overdue_percentage` increases for **three consecutive months**. This is a strong indicator of a worsening cash flow situation.

3.  **Revenue and Expense Growth Divergence:**
    *   **Recommendation:** Implement a warning for any subsidiary where the expense growth rate exceeds the revenue growth rate for **two or more consecutive months**. This points to a potential long-term profitability and cash flow problem.

### Proposed Early Warning System:

A combination of these indicators can form the basis of a robust early warning system. We propose the following alert logic:

*   **Level 1 Alert (2-3 months early warning):** Triggered if any single one of the recommended thresholds is breached. This should prompt a review of the subsidiary's financial health.
*   **Level 2 Alert (1-2 months early warning):** Triggered if any two of the recommended thresholds are breached. This should require immediate intervention and a detailed cash flow forecast review.

By implementing this data-driven early warning system, we can move from reactive crisis management to proactive risk mitigation, ensuring the financial stability of our subsidiaries and the accuracy of our overall cash flow forecasting.
