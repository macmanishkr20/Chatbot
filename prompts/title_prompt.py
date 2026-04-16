"""
Title generation prompt — produces a short, descriptive conversation title
from the first user message and first AI response (same pattern as Claude/ChatGPT).
"""

TITLE_GENERATION_PROMPT = """\
Generate a short, descriptive title for a conversation based on the user's \
first message and the assistant's first response.

Rules:
- Output ONLY the title text. No quotes, no punctuation at the end, no explanation.
- Use 3–8 words that capture the topic. Prefer noun phrases.
- Maximum {max_length} characters.
- If the exchange is just a greeting (e.g. "Hi" → "Hello! How can I help?"), \
output: "New Conversation".
- Use title case.
- Do not include the function name alone — include the topic \
(e.g. "Finance Invoice Submission Policy" not just "Finance").

Examples:
  User: "What is the leave policy in India?"
  Assistant: "According to the Talent function guidelines..."
  Title: Leave Policy India

  User: "Do I need a BRIDGE request for venue booking?"
  Assistant: "Yes, a BRIDGE request is required..."
  Title: BRIDGE Request Venue Booking

  User: "Hello!"
  Assistant: "Hello! How can I help you today?"
  Title: New Conversation

Now generate a title for:
User: {user_input}
Assistant: {ai_response}\
"""
