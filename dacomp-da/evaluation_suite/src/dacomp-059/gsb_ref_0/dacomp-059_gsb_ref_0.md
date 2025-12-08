# Analysis of High-CTR, Low-Conversion Ad Groups

## Introduction

An anomaly was detected in our ad performance data, where a subset of ad groups showed a high click-through rate (CTR) but a low conversion rate. This report details the analysis of these ad groups to identify the root causes and proposes a systematic solution to address the issue. The criteria for identifying these problematic ad groups were a CTR greater than the 75th percentile and a conversion rate less than the 25th percentile.

## Analysis and Findings

Our analysis identified **613 ad groups** that fit the high-CTR, low-conversion profile. A deep dive into these ad groups revealed a consistent pattern pointing towards a significant mismatch between user search intent and the ads being shown.

The core of the issue lies in the keyword strategy. The problematic ad groups heavily rely on **Broad Match** and **Broad Match Modifier** keyword match types. As shown in the chart below, these less restrictive match types are the most prevalent in the underperforming ad groups.

![CTR vs. Conversion Rate by Keyword Match Type](ctr_vs_conversion_by_match_type.png)

The scatter plot above visualizes the relationship between CTR and conversion rate, with each point representing an ad group. The points are color-coded by their primary keyword match type. A clear cluster of **red dots (Broad Match)** can be seen in the upper-left quadrant, representing the high-CTR, low-conversion ad groups. This visually confirms that broad match keywords are the primary drivers of this issue.

These broad match types, combined with generic keywords such as "professional", "top cheap", and "premium", cause our ads to be triggered by a wide range of irrelevant search queries. While the ad copy is compelling enough to entice a click (high CTR), the landing page content does not meet the user's expectations, leading to a quick exit and a low conversion rate.

This misalignment results in:
- **Wasted Ad Spend**: Clicks that do not convert are essentially wasted money.
- **Reduced ROI**: The overall return on investment of the campaigns is diminished.
- **Poor User Experience**: Users are frustrated when they click on an ad that doesn't lead them to a relevant page.

## Proposed Solutions

To rectify this situation and improve the overall performance of our ad campaigns, a multi-pronged approach is recommended:

### 1. Keyword Optimization
- **Implement Negative Keywords**: Proactively add negative keywords to exclude irrelevant search terms. The Search Term Report in Google Ads should be used to identify these terms.
- **Refine Match Types**: Shift budget allocation from broad match to more controlled match types like **Phrase Match** and **Exact Match**. This will target users with higher intent.
- **Enhance Keyword Specificity**: Replace overly generic keywords with more specific, long-tail keywords that better align with user intent and the solutions we provide.

### 2. Audience Segmentation
- **Review and Refine Targeting**: Analyze the audience data for the problematic ad groups. Narrow down the targeting if it's too broad.
- **Leverage Custom Audiences**: Create and target custom audiences, such as users who have visited specific pages, to deliver more tailored messaging.

### 3. Landing Page Improvements
- **Conduct A/B Testing**: The high CTR suggests the ads are effective, but the landing pages are not. Test different headlines, calls-to-action, and layouts to improve conversion rates.
- **Ensure Message Congruence**: The message on the landing page must be a seamless continuation of the ad copy that the user clicked.

### 4. Bid Adjustments
- **Adjust Bids Based on Performance**: Lower the bids for broad match keywords and other low-performing segments. Conversely, increase bids for keywords and audiences that have a proven track record of high conversion rates.

### 5. Time-of-Day Optimizations
- **Analyze Performance by Time**: Identify the days and hours that yield the best and worst performance.
- **Implement Ad Scheduling**: Restrict ad visibility to peak performance times to maximize conversion opportunities and minimize wasted spend.

## Conclusion

The issue of high CTR and low conversion rates is primarily due to an over-reliance on broad match keywords, which attract low-quality traffic. By implementing the proposed solutions, we can enhance the relevance of our ads, improve user experience, and significantly increase our conversion rates, leading to a better return on ad spend.
