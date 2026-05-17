"""Scorecard agent — typed predicate-planner analytical queries over UserScoreboard.

Routed to from the supervisor for live KPI data ("highest GTER", "my
scorecard", "show top utilisation"). Definition / methodology questions
("what is GTER", "how is utilisation calculated") go to rag_graph.

RLS rules are identical to the Expense agent (see core.rbac).
"""
