Uber 2024 Booking Peaks & Troughs: What, Why, and What to Do Next

Executive Summary
- Evening rush hour is the clear peak: 18:00 saw 12,397 bookings with a 25.4% cancellation rate; late-night trough at 04:00 saw 1,321 bookings with a 25.6% cancellation rate. Average per-km cost is relatively flat by hour (≈33.4–33.7).
- Specific peak dates spiked demand (e.g., 2024-11-16 at 462 bookings with a 19.5% cancel rate and 39.32 per-km), while trough dates showed fewer bookings and slightly higher cancel rates (e.g., 2024-05-02 at 357 bookings, 30.3% cancel rate).
- Overall, 62% of bookings completed (93,000 of 150,000), cancellations were 25% (37,500 combined), “No Driver Found” was 7% (10,500), and 6% were incomplete (9,000). Operational focus should be evening supply ramp-up, cancellation reduction, and proactive management of known peak dates.

Data & Method
- Source: SQLite table sheet1 with columns Date, Time, Booking Status, Booking Value, Ride Distance.
- Approach: Combined Date+Time into a timestamp (Python pandas), filtered to year=2024, created hourly and daily aggregates. Cancellation rate = (Cancelled by Customer + Cancelled by Driver) / total bookings. Per-km cost = Booking Value / Ride Distance for Completed rides only (excluding zero/NaN
