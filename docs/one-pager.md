# AskDB: One-Pager

## What it is
A read-only, ask-and-answer web app. Business users ask questions of a database in plain English and get back a written answer, a table and a short account of how it was worked out.

## Who it's for
Non-technical business staff. They have never written a query and want plain answers.

## What they ask
- Simple lookups ("How many orders did we ship yesterday?")
- Comparisons and trends (this quarter against last, by region)
- Rankings and breakdowns (top 10 customers by revenue)
- Follow-up questions that refine an earlier answer ("Now just show the West region")

## What they need to see
- A plain-English answer
- A table of the results
- An explanation of how the answer was worked out, so users can trust it
- Not required: charts

## What must never happen
- The app must never change data (no modify, delete or add).
- Not hard requirements, though desirable: showing restricted data, presenting wrong answers as fact, and queries that overload the database. To be confirmed.

## Out of scope
- Writing or editing data
- Saved dashboards and scheduled reports
- Forecasting and advice
- Combining the database with other data sources
