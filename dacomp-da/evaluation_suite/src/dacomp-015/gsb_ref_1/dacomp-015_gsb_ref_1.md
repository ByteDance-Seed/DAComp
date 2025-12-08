# Analysis of Home Features on Watch Count and Showings

## Executive Summary

This report analyzes the relationship between various home features and their impact on `Watch Count` and `Showings`. Our analysis reveals that while a high `Watch Count` does not strongly correlate with a higher number of `Showings`, specific property characteristics significantly influence a home's popularity and viewing frequency.

**Key Findings:**

*   **Watch Count vs. Showings:** The correlation between `Watch Count` and `Showings` is very weak (0.083), indicating that a high number of online "watches" does not reliably translate into in-person showings.
*   **Top Watched Properties:** The most-watched properties are typically 2-bedroom or 3-bedroom homes with simple or high-quality renovations, located in mid-rise buildings (6-7 stories) and facing south.
*   **Drivers of Showings:**
    *   **Floor Plan:** Homes with a larger number of bedrooms, particularly 7-bedroom and 4-bedroom configurations, tend to attract more showings.
    *   **Decoration:** The level of decoration has a less pronounced impact on showings, with "Simple renovation" and "Unfinished" properties having a slight edge. This suggests that buyers may be looking for properties they can customize.
    *   **Floor:** Very high floors (39th, 44th, 45th) and mid-rise floors receive the most showings, likely due to better views and a balance of accessibility and privacy.
    *   **Orientation:** South-facing properties are clear leaders in attracting showings, receiving significantly more a tention than any other orientation.

**Recommendations:**

*   **Marketing Strategy:** For properties with features that align with high watch counts (e.g., 2-3 bedrooms, south-facing), marketing should emphasize these popular characteristics.
*   **Showing Strategy:** To increase showings, agents should prioritize properties with a higher number of bedrooms, on very high or mid-rise floors, and with a south-facing orientation.
*   **Data Quality:** The presence of an undefined category in both `Decoration` and `Floor` with exceptionally high average showings suggests a data quality issue that needs to be addressed. Properly categorizing these properties could reveal further insights.

## Top 10 Watched Combinations

The following table presents the top 10 combinations of `Floor Plan`, `Decoration`, `Floor`, and `Orientation` that have the highest total `Watch Count`. This provides insight into what features attract the most online attention.

| Floor Plan              | Decoration            | Floor            | Orientation | Total Watch Count |
| ----------------------- | --------------------- | ---------------- | ----------- | ----------------- |
| 2 bedrooms, 1 living room | Simple renovation     | 7th floor        | South       | 3726              |
| 2 bedrooms, 1 living room | Simple renovation     | 6-story building | South       | 3582              |
| 3 bedrooms 2 living rooms | High-quality renovation | 18th floor       | South       | 3291              |
| 3 bedrooms 2 living rooms | High-quality renovation | 16th floor       | South       | 2564              |
| 3 bedrooms 2 living rooms | High-quality renovation | 6-story building | South       | 2491              |
| 3 bedrooms 2 living rooms | High-quality renovation | 11th floor       | South       | 2241              |
| 2 bedrooms, 1 living room | High-quality renovation | 7th floor        | South       | 2183              |
| 3 bedrooms 1 living room  | Simple renovation     | 6-story building | South       | 1964              |
| 2 bedrooms, 1 living room | High-quality renovation | 6-story building | South       | 1807              |
| 3 bedrooms 1 living room  | Simple renovation     | 7th floor        | South       | 1764              |

## Factors Influencing Showings

### Watch Count vs. Showings

It is a common assumption that a high number of online "watches" would lead to a higher number of in-person showings. However, our analysis shows a very weak positive correlation of **0.083** between `Watch Count` and `Showings`. The scatter plot below illustrates this relationship, with the vast majority of properties having low watch counts and low showings. This suggests that `Watch Count` alone is not a reliable predictor of showing volume.

![Watch Count vs. Showings](watch_count_vs_showings.png)

### The weak correlation between `Watch Count` and `Showings` (correlation coefficient: 0.083) indicates that a high `Watch Count` does not guarantee a high number of `Showings`. This insight is crucial for setting realistic expectations and not over-relying on `Watch Count` as a primary indicator of a property's offline interest.

### Analysis of Property Features

To understand what drives showings, we analyzed the average number of showings for different categories of `Floor Plan`, `Decoration`, `Floor`, and `Orientation`.

*   **Floor Plan:** Properties with a higher number of bedrooms tend to have more showings. For example, 7-bedroom and 4-bedroom homes have the highest average showings. This suggests that larger families or those seeking more space are more motivated to view properties.

*   **Decoration:** The impact of decoration on showings is less clear-cut. "Simple renovation" and "Unfinished" properties have slightly more showings than "High-quality" or "Luxuriously renovated" ones. This might be because buyers are looking for a "blank canvas" they can renovate to their own tastes, or they are more price-sensitive and prefer properties with lower upfront costs.

*   **Floor:** The floor level has a significant impact on showings. Very high floors (39th, 44th, 45th) and mid-rise floors are the most popular. High floors likely attract buyers with a preference for views and quiet, while mid-rise floors offer a balance of convenience and privacy.

*   **Orientation:** South-facing properties are the most popular by a significant margin. The average number of showings for south-facing homes is **2.94**, which is considerably higher than the next best orientation, Southeast (2.57). This strong preference is likely due to the desire for more natural light.

## Recommendations

Based on our findings, we propose the following recommendations for real estate agents:

1.  **Refine Marketing Strategies:**
    *   For properties with features that align with high `Watch Count` (e.g., 2-3 bedrooms, south-facing), prioritize these attributes in marketing materials to attract online attention.
    *   Do not solely rely on `Watch Count` as a measure of a property's potential for showings.

2.  **Optimize Showing Strategies:**
    *   To maximize the number of showings, focus on properties that have a higher number of bedrooms, are located on very high or mid-rise floors, and have a south-facing orientation.
    *   When advising sellers, highlight how these features can increase buyer interest and the likelihood of a viewing.

3.  **Improve Data Quality:**
    *   The presence of an undefined category in both the `Decoration` and `Floor` fields with unusually high average showings suggests a data quality issue.
    *   Investigate and properly categorize these listings to uncover potentially valuable insights that are currently hidden. This could reveal a niche market or a particularly desirable property type that is not being captured by the current data.
