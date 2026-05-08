"""Debug script — trace a single query through the RAG graph, printing each node's output."""
import asyncio
import json
import logging
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"

# Show key logs
logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
for noisy in ("httpx", "httpcore", "azure", "openai", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from langchain_core.messages import HumanMessage
from graph.rag_graph import build_rag_graph

QUERY = "How to raise a BRIDGE request?"


def _safe_print(obj, max_content=200):
    """Print state dict with truncated content fields."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "messages":
                out[k] = f"[{len(v)} message(s)]"
            elif k == "events" and isinstance(v, list):
                out[k] = f"[{len(v)} events]"
                for i, ev in enumerate(v[:3]):
                    content = (ev.get("content") or "")[:max_content]
                    out[f"  event[{i}]"] = {
                        "function": ev.get("function"),
                        "sub_function": ev.get("sub_function"),
                        "_source_type": ev.get("_source_type", "n/a"),
                        "content": content + "..." if len(ev.get("content", "")) > max_content else content,
                    }
            elif k == "parallel_results" and isinstance(v, list):
                out[k] = f"[{len(v)} function results]"
                for pr in v:
                    fn = pr.get("function", "?")
                    evts = pr.get("events", [])
                    out[f"  parallel[{fn}]"] = f"{len(evts)} events"
            elif k == "ai_content" and isinstance(v, str) and len(v) > 300:
                out[k] = v[:300] + "..."
            elif k == "multi_search_status" and isinstance(v, list):
                out[k] = v
            else:
                out[k] = v
        return out
    return obj


async def main():
    # Build graph WITHOUT checkpointer/store (stateless single-run)
    graph = build_rag_graph(checkpointer=None, memory_store=None)

    state = {
        "messages": [HumanMessage(content=QUERY)],
        "user_input": QUERY,
        "user_id": "debug@ey.com",
        "chat_id": None,
        "chat_session_id": None,
        "message_id": None,
        "input_type": "ask",
        "is_free_form": True,
        "function": [],
        "sub_function": [],
        "source_url": [],
        "start_date": "",
        "end_date": "",
        "preferred_language": "English",
        "content_type": "document",
        "requires_function_selection": False,
        "channel_type": 0,
    }

    config = {"configurable": {"thread_id": "debug-trace-001"}}

    print(f"\n{'='*70}")
    print(f"QUERY: {QUERY}")
    print(f"{'='*70}\n")

    node_count = 0
    async for chunk in graph.astream(state, config=config, stream_mode="updates"):
        for node_name, node_output in chunk.items():
            node_count += 1
            print(f"\n{'-'*60}")
            print(f"  NODE {node_count}: {node_name}")
            print(f"{'-'*60}")
            printed = _safe_print(node_output)
            for k, v in (printed if isinstance(printed, dict) else {}).items():
                if isinstance(v, (dict, list)):
                    print(f"  {k}: {json.dumps(v, indent=4, default=str, ensure_ascii=False)}")
                else:
                    print(f"  {k}: {str(v).encode('ascii', 'replace').decode()}")

    print(f"\n{'='*70}")
    print(f"TRACE COMPLETE -- {node_count} nodes executed")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())
