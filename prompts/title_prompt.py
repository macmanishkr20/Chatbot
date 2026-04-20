"""
Title generation prompt — produces a short, descriptive conversation title
from the first user message and first AI response (same pattern as Claude/ChatGPT).
"""

TITLE_GENERATION_PROMPT = """\
<task>
Generate a short, descriptive title for a conversation based on the
user's first message and the assistant's first response.
</task>

<rules>
- Output ONLY the title text — no quotes, no trailing punctuation, no
  explanation.
- Use 3–8 words that capture the topic; prefer noun phrases.
- Maximum {max_length} characters.
- Use title case.
- Do not use a function name alone — include the topic
  (e.g. "Finance Invoice Submission Policy", not just "Finance").
- If the exchange is only a greeting (e.g. "Hi" → "Hello! How can I help?"),
  output exactly: New Conversation
</rules>

<examples>

<example>
<user>What is the leave policy in India?</user>
<assistant>According to the Talent function guidelines...</assistant>
<title>Leave Policy India</title>
</example>

<example>
<user>Do I need a BRIDGE request for venue booking?</user>
<assistant>Yes, a BRIDGE request is required...</assistant>
<title>BRIDGE Request Venue Booking</title>
</example>

<example>
<user>Hello!</user>
<assistant>Hello! How can I help you today?</assistant>
<title>New Conversation</title>
</example>

</examples>

<input>
<user>{user_input}</user>
<assistant>{ai_response}</assistant>
</input>

<title>\
"""
