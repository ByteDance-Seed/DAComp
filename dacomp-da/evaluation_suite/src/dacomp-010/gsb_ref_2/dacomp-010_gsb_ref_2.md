2024 Seasonal Sales Quantity Trends and Channel Strategy for Agricultural Products

Executive Summary
- Wheat is the top-selling agricultural product in every 2024 season, with 1,177,800 units in Spring, 768,100 in Summer, 56,700 in Autumn, and 537,900 in Winter. This dominance persists despite large seasonal volume swings.
- Overall demand peaks in Spring (4,097,900 units across all categories) and declines through Summer (2,371,300) and Winter (1,778,200), with a pronounced trough in Autumn (163,100). Wheat’s share ranges from 28.7% to 34.8% depending on season.
- Channel effectiveness differs sharply by season: Spring favors E-commerce and Cooperative, Summer shifts to Direct Sales and Wholesale, and Winter is dominated by Cooperative sales. Optimizing channel allocation to these seasonal strengths can lift sales efficiency and margins.

Data and Method (Evidence)
- Tables used: core_transaction_information (Transaction Date, Sales Quantity (units), Sales Channel), basic_product_information (Agricultural Product Name), market_and_quality_feedback_inf (Season label).
- SQL steps:
  - Joined the three tables on Transaction Number and filtered 2024 transactions using strftime('%Y', [Transaction Date]) = '2024'.
  - Aggregated Sales Quantity (units) by Season label and Agricultural Product Name, saving results to season_product_units_2024.csv.
  - Identified the top product per season using a ROW_NUMBER() window over aggregated results, saving to top_product_per_season_2024.csv.
  - Computed Wheat’s channel breakdown by season, saved to wheat_channel_by_season_2024.csv.
- Python steps:
  - Pivoted seasonal product totals and built two plots (grouped bars by product/season and stacked bars for Wheat’s channel mix by season
