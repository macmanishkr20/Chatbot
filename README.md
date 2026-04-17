# MenaBot — Enterprise RAG Chatbot

A production-ready RAG chatbot built on **FastAPI + LangGraph** (Python backend) and **Angular 19** (frontend), with Azure SQL for persistence, Azure OpenAI for LLM, and Azure AI Search for retrieval.

---

## Table of Contents

1. [Overview](#overview)
2. [Tech Stack](#tech-stack)
3. [System Architecture](#1-system-architecture-block-diagram)
4. [Frontend Component Tree](#2-frontend-component-tree--state-flow)
5. [Send Message Flow](#3-send-message-flow-end-to-end-sse)
6. [Edit / Regenerate Flow](#4-edit--regenerate-flow-checkpoint-branching)
7. [LangGraph RAG Pipeline](#5-langgraph-rag-pipeline-node-level-detail)
8. [Feature Inventory](#feature-inventory)
9. [Getting Started](#getting-started)
10. [Project Structure](#project-structure)
11. [Key Design Decisions](#key-design-decisions)

---

## Overview

MenaBot is a domain-scoped Retrieval-Augmented Generation (RAG) chatbot designed for enterprise internal use. It supports:

- **Streaming answers** over Server-Sent Events with live chain-of-thought steps
- **Full conversation history** with edit-and-branch and regenerate-response
- **Checkpointed state** via LangGraph persisted in Azure SQL
- **Citations** drawn from a curated Azure AI Search knowledge base
- **Feedback loops** (thumbs up / down + freeform comments)
- **Multi-user isolation** by `user_id` and `chat_session_id`

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Angular 19 (standalone components, signals, OnPush CD) |
| Styling | SCSS |
| Markdown | `marked` |
| Backend | FastAPI (Python 3.11+) |
| Orchestration | LangGraph + LangChain |
| LLM | Azure OpenAI (GPT-4 / configurable deployment) |
| Retrieval | Azure AI Search (hybrid semantic + keyword) |
| Persistence | Azure SQL Database (pyodbc) |
| Streaming | Server-Sent Events (SSE) |
| State Mgmt (FE) | Angular Signals |

---

## 1. System Architecture (Block Diagram)

```mermaid
graph TB
    subgraph Browser["Browser (User)"]
        UI["Angular 19 SPA<br/>(Signals + Standalone Components)"]
    end

    subgraph Frontend["Angular Frontend (menabot-ui)"]
        direction TB
        AppShell["AppShellComponent<br/>(sidebar + main)"]
        Login["LoginComponent<br/>(email auth)"]
        ChatWin["ChatWindowComponent"]

        subgraph Services_FE["Services Layer"]
            ChatSvc["ChatService<br/>SSE streaming + state signals"]
            ApiSvc["ApiService<br/>HTTP + fetch"]
            AuthSvc["AuthService<br/>session"]
            ThemeSvc["ThemeService<br/>dark/light"]
        end
    end

    subgraph Backend["FastAPI Backend (Python)"]
        direction TB
        subgraph Endpoints["REST + SSE Endpoints"]
            E1["POST /chat (SSE)"]
            E2["POST /chat/edit (SSE)"]
            E3["POST /chat/regenerate"]
            E4["POST /chat/cancel"]
            E5["GET /conversations"]
            E6["GET /messages"]
            E7["DELETE /conversations"]
            E8["PATCH /rename"]
            E9["POST /feedback"]
        end

        subgraph Graph["LangGraph Pipeline"]
            Supervisor["Supervisor Node"]
            Classifier["Intent Classifier"]
            Retriever["Retriever Node"]
            Generator["Generator Node<br/>(LLM stream)"]
            Persist["Persist Node"]
        end

        subgraph GraphState["Checkpointer"]
            CP["AzureSQLCheckpointSaver<br/>thread_id = userId_sessionId<br/>base64 serde"]
        end
    end

    subgraph Azure["Azure Cloud"]
        SQL[("Azure SQL DB<br/>Conversations / Messages<br/>LangGraphCheckpoints / Feedback")]
        AOAI["Azure OpenAI<br/>(GPT-4 / Embeddings)"]
        Search["Azure AI Search<br/>(RAG knowledge base)"]
    end

    UI --> AppShell
    AppShell --> Login
    AppShell --> ChatWin
    ChatWin --> ChatSvc
    ChatSvc --> ApiSvc
    ChatSvc --> AuthSvc
    AppShell --> ThemeSvc

    ApiSvc -.SSE.-> E1
    ApiSvc -.SSE.-> E2
    ApiSvc --> E3
    ApiSvc --> E4
    ApiSvc --> E5
    ApiSvc --> E6
    ApiSvc --> E7
    ApiSvc --> E8
    ApiSvc --> E9

    E1 --> Supervisor
    E2 --> Supervisor
    E3 --> Supervisor
    Supervisor --> Classifier
    Classifier --> Retriever
    Retriever --> Generator
    Generator --> Persist

    Retriever --> Search
    Generator --> AOAI
    Persist --> SQL
    CP <--> SQL
    Graph <--> CP
    E5 --> SQL
    E6 --> SQL
    E7 --> SQL
    E8 --> SQL
    E9 --> SQL
```

---

## 2. Frontend Component Tree & State Flow

```mermaid
graph TD
    Root["main.ts -> bootstrapApplication"]
    Root --> AppComp["AppComponent"]
    AppComp -->|AuthGuard| AppShell["AppShellComponent"]
    AppComp -.unauthenticated.-> LoginC["LoginComponent"]

    AppShell --> Sidebar["Sidebar Panel<br/>conversations list<br/>New Chat button<br/>theme toggle<br/>user menu"]
    AppShell --> Main["Main Area"]
    Main --> ChatWindow["ChatWindowComponent"]

    ChatWindow --> MsgList["Messages Loop"]
    ChatWindow --> ChatInput["ChatInputComponent<br/>textarea<br/>stop button"]

    MsgList --> Bubble["MessageBubbleComponent<br/>(per message)"]

    Bubble --> Markdown["Markdown Pipe<br/>marked renderer"]
    Bubble --> Thinking["ThinkingPanelComponent<br/>collapsible steps"]
    Bubble --> Suggest["SuggestiveActionsComponent<br/>follow-up chips"]
    Bubble --> FBModal["FeedbackModalComponent<br/>thumbs + comments"]
    Bubble --> Citations["Citations footer<br/>[1][2] refs"]
    Bubble --> EditBox["Edit mode<br/>inline textarea<br/>regenerate btn"]

    subgraph State["ChatService Signals (Reactive State)"]
        direction LR
        S1["messages()"]
        S2["conversations()"]
        S3["activeSessionId()"]
        S4["activeChatId()"]
        S5["isStreaming()"]
        S6["conversationTitle()"]
        S7["sidebarOpen()"]
        S8["error()"]
        S9["userMessageCount()"]
    end

    ChatWindow -.reads.-> S1
    ChatWindow -.reads.-> S5
    Sidebar -.reads.-> S2
    Sidebar -.reads.-> S3
    Bubble -.reads.-> S1
    ChatInput -.writes.-> S1
```

---

## 3. Send Message Flow (End-to-End SSE)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant CI as ChatInput
    participant CS as ChatService
    participant API as ApiService
    participant BE as FastAPI /chat
    participant G as LangGraph
    participant CP as Checkpointer
    participant LLM as Azure OpenAI
    participant SQL as Azure SQL
    participant MB as MessageBubble

    U->>CI: Type "What is AWS?" + Enter
    CI->>CS: sendMessage(text)
    CS->>CS: messages.update(+ userMsg)
    CS->>CS: isStreaming = true
    CS->>CS: create placeholder assistantMsg
    CS->>API: streamChat(body, AbortSignal)
    API->>BE: POST /chat (fetch, SSE)

    BE->>CP: aget(thread_id = userId_sessionId)
    CP->>SQL: SELECT checkpoint
    SQL-->>CP: (empty for new chat)
    CP-->>BE: no state

    BE->>G: astream(initial_state)

    loop Per graph node
        G->>BE: node start
        BE-->>API: data: {"type":"thought","node":"classifier","message":"Classifying..."}
        API-->>CS: event
        CS->>MB: thinkingSteps += step
    end

    G->>LLM: chat completion (stream)
    loop Token streaming
        LLM-->>G: token chunk
        G-->>BE: content chunk
        BE-->>API: data: {"type":"content","content":"AWS is..."}
        API-->>CS: event
        CS->>MB: content += chunk
    end

    G->>CP: aput(new checkpoint)
    CP->>SQL: INSERT/UPDATE checkpoint (base64)
    G->>SQL: INSERT Conversations + Messages
    SQL-->>G: chat_id, message_id

    G-->>BE: final state
    BE-->>API: data: {"type":"final","chat_id":42,"message_id":"...","suggestive_actions":[...]}
    API-->>CS: final event
    CS->>CS: activeChatId.set(42)
    CS->>CS: messages.update(finalize: citations, suggestions)
    CS->>API: GET /conversations (refresh sidebar)
    CS->>CS: isStreaming = false
    CS->>MB: thinkingCollapsed = true
    U->>MB: sees final answer + citations + suggestions
```

---

## 4. Edit / Regenerate Flow (Checkpoint Branching)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant MB as MessageBubble
    participant CS as ChatService
    participant BE as FastAPI /chat/edit
    participant CP as Checkpointer
    participant G as LangGraph
    participant SQL as Azure SQL

    rect rgb(239, 246, 255)
        Note over U,MB: EDIT: User clicks edit on their 2nd message
        U->>MB: toggleEdit(msgId)
        MB->>MB: isEditing = true, show textarea
        U->>MB: Types new text + Save
        MB->>CS: editMessage(index=1, newText)
        CS->>CS: truncate messages from edit point
        CS->>CS: messages.update(kept + updatedUserMsg)
    end

    CS->>BE: POST /chat/edit<br/>{user_id, chat_session_id,<br/>message_index: 1, new_input}

    rect rgb(254, 243, 199)
        Note over BE,CP: Load existing checkpoint
        BE->>CP: aget(thread_id)
        CP->>SQL: SELECT checkpoint
        SQL-->>CP: serialized state (base64)
        CP->>CP: serde.loads_typed() -> BaseMessage[]
        CP-->>BE: current_state
    end

    alt Checkpoint has messages
        BE->>BE: _ensure_base_messages(msgs)
        BE->>BE: user_msg_positions = [0, 2, 4]
        BE->>BE: edit_pos = positions[1] = 2
        BE->>BE: kept = messages[:2]<br/>+ RemoveMessage for rest<br/>+ HumanMessage(new_input)
        BE->>BE: trim_messages_to_budget(kept)
        BE->>G: astream(branched_state)
    else No messages found (empty/legacy)
        BE->>BE: _build_fresh_state_from_edit()
        BE->>BE: log "treating edit as new turn"
        BE->>G: astream(fresh_state)
    end

    loop Same SSE stream as /chat
        G-->>BE: thought / content events
        BE-->>CS: SSE events
        CS->>MB: update streaming UI
    end

    G->>CP: aput(new branched checkpoint)
    CP->>SQL: UPSERT (overwrites old branch)
    G->>SQL: INSERT new Message row
    BE-->>CS: final event
    CS->>MB: show regenerated response

    rect rgb(236, 253, 245)
        Note over U,SQL: REGENERATE follows the same flow<br/>but drops only the LAST assistant message,<br/>keeps user prompt, re-runs graph
    end
```

---

## 5. LangGraph RAG Pipeline (Node-Level Detail)

```mermaid
flowchart LR
    Start([User Query Enters<br/>/chat endpoint]) --> State["Build RAGState<br/>messages, user_id,<br/>chat_session_id, filters"]

    State --> Super["Supervisor Node<br/>entry point"]

    Super --> Classify{"Intent Classifier<br/>ask / clarify /<br/>greeting / out-of-scope"}

    Classify -->|greeting| Greet["Greeting Node<br/>canned response"]
    Classify -->|out-of-scope| Reject["Reject Node<br/>polite decline"]
    Classify -->|clarify| Ambig["Ambiguity Check<br/>ask follow-up"]
    Classify -->|ask| Retrieve

    Retrieve["Retriever Node<br/>Azure AI Search<br/>semantic + keyword<br/>filters: function,<br/>sub_function, date"]

    Retrieve --> Rerank["Rerank + Dedupe<br/>top-K chunks"]
    Rerank --> Gen["Generator Node<br/>Azure OpenAI GPT-4<br/>system prompt + context<br/>streams tokens"]

    Gen --> Cite["Citation Builder<br/>[1][2] -> URL map"]
    Cite --> Sugg["Suggestive Actions<br/>follow-up hints"]

    Greet --> Persist
    Reject --> Persist
    Ambig --> Persist
    Sugg --> Persist

    Persist["Persist Node<br/>Conversations row<br/>Messages row<br/>chat_session_id stored"]

    Persist --> CP["Checkpoint<br/>base64 serde.dumps_typed<br/>-> LangGraphCheckpoints"]

    CP --> Final([SSE final event<br/>-> frontend])
```

---

## Feature Inventory

| Area | Feature | Where Implemented |
|------|---------|-------------------|
| **Auth** | Email login, session persistence | `AuthService`, `LoginComponent`, `AuthGuard` |
| **Chat** | Send message w/ SSE streaming | `ChatService.sendMessage` -> `/chat` |
| **Chat** | Thinking steps (chain-of-thought) | `ThinkingPanelComponent` + `thought` events |
| **Chat** | Live token streaming | `content` events -> signal updates |
| **Chat** | Citations `[1][2] URL` | `parseCitations()` -> footer |
| **Chat** | Suggestive follow-ups | `SuggestiveActionsComponent` |
| **Chat** | Cancel in-flight stream | `AbortController` + `/chat/cancel` |
| **Chat** | Edit any user message | `editMessage()` -> `/chat/edit` w/ checkpoint branching |
| **Chat** | Regenerate last response | `regenerate()` -> `/chat/regenerate` |
| **Chat** | Markdown rendering | `markdown.pipe.ts` + `marked` |
| **History** | Conversation sidebar | `/conversations` -> `ChatService.conversations` signal |
| **History** | Load past chat | `/messages` + restore `chat_session_id` |
| **History** | Rename conversation | `PATCH /rename` |
| **History** | Delete conversation | `DELETE /conversations/:id` |
| **Feedback** | Thumbs up/down + comments | `FeedbackModalComponent` -> `/feedback` |
| **UI/UX** | Dark/light theme | `ThemeService` |
| **UI/UX** | Sidebar toggle (mobile) | `sidebarOpen` signal |
| **Backend** | LangGraph checkpointing | `AzureSQLCheckpointSaver` (base64 serde) |
| **Backend** | Thread keying | `thread_id = userId_chatSessionId` |
| **Backend** | SQL persistence | `Conversations`, `Messages`, `Feedback` tables |
| **Backend** | Retrieval | Azure AI Search |
| **Backend** | LLM | Azure OpenAI (configurable deployment) |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+
- Azure SQL Database with ODBC driver 18
- Azure OpenAI endpoint + API key
- Azure AI Search endpoint + admin key

### Backend Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in AZURE_SQL_*, AZURE_OPENAI_*, AZURE_SEARCH_* variables

# Run the API
python app.py
# or with uvicorn
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The backend will:
- Auto-create `Conversations`, `Messages`, `LangGraphCheckpoints`, `Feedback` tables on first run
- Apply any pending column migrations (e.g. `ChatSessionId`)
- Listen on `http://localhost:8000`

### Frontend Setup

```bash
cd demo/menabot-ui
npm install
npm start
```

Dev server runs on `http://localhost:4200`.

### Environment Variables (Backend)

| Variable | Description |
|----------|-------------|
| `AZURE_SQL_SERVER` | Azure SQL server hostname |
| `AZURE_SQL_DATABASE` | Database name |
| `AZURE_SQL_USERNAME` | SQL user |
| `AZURE_SQL_PASSWORD` | SQL password |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource URL |
| `AZURE_OPENAI_API_KEY` | API key |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name (e.g. `gpt-4o`) |
| `AZURE_OPENAI_API_VERSION` | e.g. `2024-08-01-preview` |
| `AZURE_SEARCH_ENDPOINT` | Azure AI Search URL |
| `AZURE_SEARCH_API_KEY` | Admin key |
| `AZURE_SEARCH_INDEX` | Index name |
| `MAX_INPUT_LENGTH` | Max chars per user query |
| `RATE_LIMIT_PER_MINUTE` | Per-user request cap |

---

## Project Structure

```
.
├── app.py                          # FastAPI entry + endpoint handlers
├── config.py                       # Environment + constants
├── requirements.txt
├── graph/
│   ├── state.py                    # RAGState TypedDict
│   ├── context_manager.py          # Token-budget trimming
│   └── nodes/
│       ├── supervisor.py           # Graph builder + routing
│       ├── classifier.py
│       ├── retriever.py
│       ├── generator.py
│       └── persist_node.py         # Saves to Conversations/Messages
├── models/
│   └── chat_models.py              # Pydantic request/response schemas
├── services/
│   ├── sql_client.py               # Azure SQL CRUD (pyodbc)
│   └── checkpointer.py             # AzureSQLCheckpointSaver (sync + async)
└── demo/menabot-ui/                # Angular 19 frontend
    ├── angular.json
    ├── package.json
    └── src/app/
        ├── app.component.ts
        ├── app.routes.ts
        ├── components/
        │   ├── app-shell/
        │   ├── login/
        │   ├── chat-window/
        │   ├── chat-input/
        │   ├── message-bubble/
        │   ├── thinking-panel/
        │   ├── suggestive-actions/
        │   └── feedback-modal/
        ├── services/
        │   ├── chat.service.ts     # Central state + SSE orchestrator
        │   ├── api.service.ts      # HTTP/fetch wrapper
        │   ├── auth.service.ts
        │   └── theme.service.ts
        ├── guards/
        │   └── auth.guard.ts
        ├── models/
        │   └── chat.models.ts      # TypeScript interfaces
        └── pipes/
            └── markdown.pipe.ts
```

---

## Key Design Decisions

### 1. `chat_session_id` vs `chat_id`

Two distinct identifiers with different lifecycles:

| ID | Source | Purpose |
|----|--------|---------|
| `chat_session_id` | Frontend-generated (`session_<ts>_<rand>`) | LangGraph thread key for checkpoints |
| `chat_id` | Azure SQL auto-increment | Row ID of `Conversations` table |

**Why both?** LangGraph needs the thread key *before* the first response is persisted, but `chat_id` only exists after the persist node runs. The `ChatSessionId` column on `Conversations` stores the original thread key so loaded conversations can resume their checkpoint for edit / regenerate.

### 2. Checkpoint Serialization (base64)

Earlier versions used `json.dumps(checkpoint, default=str)`, which stringified `BaseMessage` objects into their `repr()` form and broke round-tripping. Current implementation uses LangGraph's native `JsonPlusSerializer`:

```python
type_str, data_bytes = self.serde.dumps_typed(checkpoint)
payload = {
    "_type": type_str,
    "_encoding": "base64",
    "_data": base64.b64encode(data_bytes).decode("ascii"),
}
```

Base64 avoids lone-surrogate encoding issues with Azure SQL NVARCHAR columns. Legacy surrogateescape rows are still decoded transparently for backward compatibility.

### 3. SSE over POST (not EventSource)

`EventSource` only supports GET. We use `fetch` + `ReadableStream` so we can POST the request body containing `user_input`, filters, etc., while still consuming Server-Sent Events.

### 4. Angular Signals + OnPush

Every component is `ChangeDetectionStrategy.OnPush`. State lives exclusively in `ChatService` signals — no component-local duplication. This gives:

- Deterministic re-rendering (only components whose read signals change)
- Minimal CD overhead even with long chat histories
- Time-travel debugging is feasible (signals are snapshottable)

### 5. Edit as a Graph Branch

Editing a user message does **not** mutate existing SQL rows. Instead:

1. Load the last checkpoint
2. Reconstruct proper `BaseMessage` objects (handles legacy repr strings)
3. Find the absolute index of the Nth `HumanMessage`
4. Keep messages up to that point, append `RemoveMessage` for the rest
5. Append the edited `HumanMessage` and re-run the graph

The new checkpoint overwrites the old one at the same `thread_id` — effectively branching the conversation in place.

### 6. Graceful Fallback on Empty Checkpoints

If the checkpoint is missing or empty (legacy rows, DB reset), the edit endpoint logs a warning and treats the edit as a fresh chat turn rather than returning a 400 error. This makes the UI resilient against stale state.

---

## License

Internal project — see LICENSE file for terms.
