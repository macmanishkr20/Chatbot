"""LMS (Leave Management System) agent — handles user-specific leave data queries.

For policy / definitional questions ("what is the paternity leave policy?")
the supervisor routes to rag_graph instead. This agent is strictly for
transactional / read-only data queries:

  - Leave balance (per leave type)
  - My leave applications (history, status)
  - Pending leave approvals (for managers)

Backend selection is config-driven (LMS_DATA_SOURCE_KIND). Today: stub
or HTTP. Tomorrow: SQL — adding it is a single new file under
data_sources/, no agent code changes.
"""
