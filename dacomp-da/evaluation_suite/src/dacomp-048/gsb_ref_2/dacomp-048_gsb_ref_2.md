Executive Summary

Vocational school job postings show a concentrated starting salary range with standard benefits widely offered. Two qualities—prior work experience and technical roles—are associated with significantly higher starting base salaries. Commission-based roles tend to have lower starting bases, and foreign language requirements show negligible impact on base salaries.

Data & Method

- Scope: 9,073 postings where Education Requirement = “Vocational school or above” (SQL filter on sheet1.Education Requirement).
- Salary parsing: Starting salary defined as the lower bound of Base salary (if present) or the lower bound of the listed monthly range (Python parse of Salary Range).
- Benefits parsing: Tokenized Benefits by commas/“and”, then counted frequencies.
- Qualities tested: Work Experience Requirement, Foreign Language Requirement, and whether the Job Title indicates a technical role; also commission pay structures and select benefit flags.
- Statistical rigor: Mann–Whitney U tests performed on starting base salaries across groups.

Starting Salary Distribution (Vocational School Graduates
