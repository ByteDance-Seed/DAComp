China’s Industrial Water Consumption Share vs Economic Development: What the Data Shows and Why It Matters

Executive Summary
- Nationally, the industrial water consumption share stayed roughly flat around ~21% while per capita GDP rose from 7,316 to 35,911 yuan/person (2000–2018). The correlation between share and per capita GDP is weakly negative (r = -0.147), implying mild decoupling.
- Across provinces/municipalities (pooled over time), higher economic development is modestly associated with a higher industrial water share (r = 0.322). However, there is strong regional heterogeneity: 16 regions show negative correlations (<= -0.3), 8 are weak (-0.3 to 0.3), and 7 are positive (>= 0.3).
- Tier-1 cities and coastal industrial economies (e.g., Beijing, Shanghai, Guangdong) show strong negative relationships, consistent with industrial upgrading, service sector expansion, and improved water efficiency. Several inland/resource-oriented provinces (e.g., Ningxia, Xinjiang, Tibet) show strong positive relationships, suggesting industrial expansion raises the share of industrial water in total use.

Data and Method (Evidence)
- Data tables and fields used:
  - Water: sheet1 fields “Industrial Water Consumption (100 million m³)” and “Total Water Consumption (100 million m³) ” (note trailing space), and identifiers “Year”, “Region Code”, “Region Name”.
  - Economy: economic_indicator_data field “Per capita GDP (yuan/person)” plus “Year” and “Region Code”.
- Computation:
  - Industrial share (%) = Industrial Water Consumption / Total Water Consumption × 100.
  - Join via Year + Region Code; separate “China” national aggregate vs. provinces/municipalities.
  - Metrics: Pearson correlations nationally and pooled across provinces, plus region-level correlations.

Key Findings with Visuals

1) National trend (2000–2018
