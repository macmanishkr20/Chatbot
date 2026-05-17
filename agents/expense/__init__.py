"""Expense agent — typed predicate-planner analytical queries over UserExpenses.

Routed to from the supervisor for live expense data queries (highest claim,
totals, listings). Knowledge / policy questions ("what is the per-diem cap")
go to rag_graph instead.

RLS: rank_code ∈ {11, 13} → may query any GUI; other ranks are
auto-restricted to their own GUI via the SQL compiler's
``security_predicates`` mechanism.
"""
