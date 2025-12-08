Executive Summary
• The portfolio is under budget on average: mean cost deviation (Budget − Actual) is +45.03, with median +7.6 and total under-spend of 13,462.9 across 299 projects (Budget Amount=51,351.2 vs Actual Cost=37,888.3). Overspend rate is 16.7%. 
• Cost outcomes vary substantially by Project Type and Risk Level: Infrastructure and Software Development are more under budget than Marketing, while High Risk projects overspend far more frequently (42%) and have the lowest satisfaction (6.73). 
• Team Size and Customer Satisfaction relate meaningfully to cost deviation: larger teams correlate with greater under-budget outcomes (corr=+0.416), and higher under-budget outcomes correlate with lower satisfaction (corr=−0.225), indicating potential under-investment trade-offs.

Data and Method
• Data source: sheet1 table in dacomp-en-008.sqlite. Key fields used: Budget Amount, Actual Cost, Project Type, Team Size, Risk Level, Customer Satisfaction. 
• Metric definitions: cost deviation = Budget Amount − Actual Cost; overspend when deviation < 0. 
• Steps: SQL to validate scope and compute grouped aggregates; Python (pandas/matplotlib
