"""
Conversation-title generation prompt.

Used by graph/nodes/title_node.py to produce a short Claude/ChatGPT-style
title from the first user/assistant exchange.
"""

TITLE_GENERATION_PROMPT = """\
You are generating a concise title for a chat conversation.

Rules:
- Output ONLY the title text — no quotes, no punctuation at the end,
  no prefix like "Title:".
- Title must be {max_length} characters or fewer.
- Aim for 3 to 8 words that capture the user's main intent.
- Use Title Case where natural; avoid trailing periods.
- Do not invent details that are not present in the messages.

User's first message:
\"\"\"{user_input}\"\"\"

Assistant's first reply:
\"\"\"{ai_response}\"\"\"

Title:"""
