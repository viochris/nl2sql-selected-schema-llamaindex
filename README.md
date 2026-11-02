# 🗄️ NL2SQL with Selected Schema Retrieval (LlamaIndex)

Ask questions about a PostgreSQL database in plain language and get answers back. These two CLI scripts store the description of each table in ChromaDB Cloud, retrieve only the few tables that match the question, let Gemini write the SQL from those tables, run it, and explain the result. One script answers single questions, and the other keeps a conversation in PostgreSQL so follow-up questions work.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat&logo=python&logoColor=white)
![LlamaIndex](https://img.shields.io/badge/Framework-LlamaIndex-6E56CF?style=flat)
![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB%20Cloud-FF6F00?style=flat)
![Gemini](https://img.shields.io/badge/LLM-Google%20Gemini-4285F4?style=flat&logo=googlegemini&logoColor=white)
![LiteLLM](https://img.shields.io/badge/Routing-LiteLLM-black?style=flat)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-336791?style=flat&logo=postgresql&logoColor=white)
![Phoenix](https://img.shields.io/badge/Tracing-Arize%20Phoenix-purple?style=flat)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

## 📌 Overview

This repository contains two CLI scripts that translate natural language questions into SQL (NL-to-SQL) for a PostgreSQL database. Both are built on LlamaIndex and share one core idea called **selected schema retrieval**.

To write correct SQL, an LLM has to know the table names, the columns, the data types, and how values are written in the data. The simplest approach is to put the structure of every table into every prompt. That works for a small database, but the prompt gets longer, noisier, and more expensive with each table you add. Here, the description of each table is embedded once and stored in ChromaDB Cloud. When a question arrives, only the closest matching table descriptions (the top 3) are retrieved, and only those are given to the LLM.

| Script | Mode | What it does |
| :--- | :--- | :--- |
| `selected-schema-query.py` | Single turn | Handles each question on its own. Retrieves the relevant schemas, generates the SQL, runs it, and prints the answer |
| `selected-schema-chat.py` | Multi turn | Does the same, but wraps it in a chat engine whose history is stored in PostgreSQL, so follow-ups such as "only the summer ones" can be understood |

Both scripts follow the same skeleton:

1. Load `.env` and stop with a clear error that names any missing variable.
2. Configure the LLM (Gemini through LiteLLM), the embedding model, the token counter, and the debug handler.
3. Register Phoenix tracing, so every run is recorded as a trace.
4. Connect to ChromaDB Cloud and PostgreSQL, then print the tables found.
5. Build the table schema index in ChromaDB, or load it if it already exists.
6. Create the query engine (and, in the chat script, the chat engine with memory).
7. Run an interactive loop in the terminal until you type an exit word.
8. For every question, print the answer, the generated SQL, the source nodes (the rows the database returned), the token usage, and the estimated cost.
9. If anything fails, print the traceback and a categorized summary, then exit with code 1.

This repository uses `SQLTableRetrieverQueryEngine`. LlamaIndex also offers `NLSQLTableQueryEngine`, which takes a different approach. The difference is explained in [Two Approaches to NL-to-SQL](#-two-approaches-to-nl-to-sql).

### ✨ Key Features
* 🎯 **Selected schema retrieval.** Only the 3 most relevant table schemas are retrieved for each question, instead of the whole database structure.
* ✍️ **Hand-written table context.** The `dresses` table has a detailed description with its allowed values, the meaning of each column, and the exact spelling of unusual column names.
* ♻️ **Index built once.** If the ChromaDB collection already has data, the scripts load the stored index and skip embedding.
* 💬 **Two modes.** A single-turn script, and a multi-turn script whose chat history is stored in PostgreSQL.
* 🔁 **Model fallback.** LiteLLM calls `gemini/gemini-2.5-flash` first, retries twice, and falls back to `gemini/gemini-3.5-flash`.
* 🔍 **Transparent answers.** Every answer is printed together with the generated SQL and the raw rows the database returned.
* 📊 **Token and cost tracking.** Token counts come from LlamaIndex's callback handler, and the cost is estimated per question from the LLM responses.
* 🛰️ **Phoenix tracing.** Each script sends its traces to its own Phoenix project, so every step of a run can be inspected.
* 🛡️ **Categorized error handling.** Database, quota, authentication, network, and processing errors each get a readable summary after the raw traceback.

---

## 🎯 Context & Problem Statement

### 📖 The Problem

A language model has never seen your database. To answer "how many party dresses have a rating above 4.5?" it must write a SQL query, and for that it needs the exact table and column names and the way values are stored. Building this reliably runs into five practical problems.

1. **The full schema in every prompt does not scale.** Putting every table's structure into each prompt makes it longer and noisier as the database grows. That raises the cost and gives the model more irrelevant text to be distracted by.
2. **Auto-generated schemas carry no meaning.** A raw schema lists names and types only. It does not say that `Price` is a tier such as `'low'` or `'very-high'` and not a number, that text values are lowercase, that a `Rating` of `0.0` usually means no reviews yet, that one column is spelled `waiseline`, or that `"Pattern Type"` contains a space and must be quoted. Without this knowledge, the generated SQL is often wrong.
3. **A single question has no context.** A follow-up such as "now only the summer ones" means nothing if every question is processed on its own.
4. **Conversation history disappears.** If the history lives only in the running process, it is gone when the script ends.
5. **It is hard to see what happened and what it cost.** Without tracing and token counting, you cannot tell which model answered, how many tokens a question used, or what it cost.

### 💡 The Solution

Each problem above is handled by one specific part of the pipeline, and each part also has a known gap.

| Problem | How this repo handles it | What is still missing |
| :--- | :--- | :--- |
| 1. Full schema in every prompt | Each table description is embedded and stored in ChromaDB. Only the top 3 closest schemas are retrieved for each question | The sample has one described table, so retrieval always returns that table. The benefit appears once several tables exist |
| 2. Schemas without meaning | `table_context_dict` replaces the auto-generated description with a hand-written one | Only `dresses` has one. Other tables use the default description |
| 3. No context in single questions | The chat script wraps the query engine in `CondenseQuestionChatEngine`, which rewrites a follow-up into a standalone question | The rewrite is done by the LLM, so an unclear follow-up can still be misread |
| 4. Lost history | Chat history is stored in a PostgreSQL table through `Memory` | The session id is fixed in the script, so every run continues the same conversation |
| 5. Hidden behavior and cost | Phoenix tracing, `TokenCountingHandler`, and a per-question cost estimate from LiteLLM | Token counts use an OpenAI tokenizer, so they are approximate for Gemini |

---

## 🧠 Core Concepts Explained

If NL-to-SQL or LlamaIndex is new to you, this table explains the terms used in the rest of the README.

| Concept | Plain-language explanation | Where you see it |
| :--- | :--- | :--- |
| **NL-to-SQL** | Natural language to SQL. A question in plain words is translated into a SQL query, which is then run on the database | Both scripts |
| **Schema** | The structure of a table: its name, its columns, and the data type of each column | Both scripts |
| **Table context (`context_str`)** | A hand-written description of a table that replaces the auto-generated one. It can state allowed values, meanings, and spelling rules | `table_context_dict` |
| **`SQLDatabase`** | A LlamaIndex wrapper around a SQLAlchemy engine. It lets LlamaIndex read table structures and run queries | Both scripts |
| **`SQLTableSchema`** | An object that represents one table, with its name and an optional `context_str` | Both scripts |
| **`SQLTableNodeMapping`** | Converts each `SQLTableSchema` into a node that can be embedded, and converts a retrieved node back into a table | Both scripts |
| **`ObjectIndex`** | An index over objects (here, table schemas) instead of plain text. It embeds each object and returns the closest ones for a question | Both scripts |
| **Embedding** | A list of numbers that represents the meaning of a text. Texts with similar meaning get similar numbers, which makes search by meaning possible | `models/gemini-embedding-2` |
| **Chunking** | Splitting long text into smaller pieces before embedding. It is not used here, because each table description is embedded as one piece (1 schema = 1 embedding) | Disabled, noted in the code |
| **Chroma collection** | A named container inside ChromaDB that holds vectors, much like a table in a database | `sql_tables_query_schema`, `sql_table_chat_schema` |
| **Retriever and top-k** | Finding the items whose embeddings are closest to the question. `similarity_top_k=3` means "return the 3 closest" | `obj_index.as_retriever(similarity_top_k=3)` |
| **`SQLTableRetrieverQueryEngine`** | A query engine that retrieves the relevant table schemas, asks the LLM to write SQL using only those, runs the SQL, and writes the answer | Both scripts |
| **`CondenseQuestionChatEngine`** | A chat engine that uses the chat history to rewrite each new message as a standalone question, then sends it to a query engine | Chat script |
| **`Memory`** | LlamaIndex's conversation memory. With `async_database_uri`, the history is stored in a database table. `token_limit` caps how much history is kept | Chat script |
| **LiteLLM** | A library that offers one interface to many LLM providers. Here it calls Gemini and handles retries and the fallback model | Both scripts |
| **Fallback and retries** | `num_retries` repeats a failed call. `fallbacks` names a second model to try when the first keeps failing | `additional_kwargs` of `LiteLLM` |
| **`drop_params`** | A LiteLLM option that drops request parameters a model does not support, instead of raising an error | `additional_kwargs` of `LiteLLM` |
| **Trace** | A step-by-step record of what happened inside a run. Arize Phoenix collects traces and shows them in a web interface | `register(...)` and `LlamaIndexInstrumentor` |
| **`TokenCountingHandler`** | A LlamaIndex callback that counts the tokens sent to and received from the LLM | Both scripts |
| **`LlamaDebugHandler`** | A LlamaIndex callback that records LLM inputs and outputs. The scripts read its events to calculate the cost | Both scripts |
| **`nest_asyncio`** | Allows async code to run in environments where an event loop is already running | Both scripts |

---

## 🧩 Tech Stack Highlights

| Layer | Tool | Role |
| :--- | :--- | :--- |
| **Orchestration** | LlamaIndex core (`Settings`, `SQLDatabase`, `VectorStoreIndex`, `StorageContext`, `ObjectIndex`) | Global configuration, schema indexing, and retrieval |
| **Query engines** | `SQLTableRetrieverQueryEngine`, `CondenseQuestionChatEngine` | SQL generation over retrieved schemas, and conversation handling |
| **LLM** | LiteLLM with `gemini/gemini-2.5-flash` (fallback `gemini/gemini-3.5-flash`) | SQL writing, question rewriting, and answer synthesis |
| **Text embeddings** | `GoogleGenAIEmbedding` (`models/gemini-embedding-2`) | Embeds the table schemas and the questions |
| **Vector storage** | ChromaDB Cloud (`chromadb.CloudClient`, `ChromaVectorStore`) | Stores the table schema embeddings |
| **Database** | PostgreSQL through SQLAlchemy | Holds the data and receives the generated SQL |
| **Conversation memory** | `Memory` + AsyncPG (PostgreSQL) | Chat history across runs (chat script only) |
| **Observability** | Arize Phoenix (`phoenix.otel`, OpenInference LlamaIndex instrumentor) | Traces of every run |
| **Metrics** | `TokenCountingHandler` with `tiktoken`, `LlamaDebugHandler`, `litellm.completion_cost` | Token counts and cost estimate |
| **Config & runtime** | `python-dotenv`, `nest-asyncio`, `asyncio` | Loads secrets from `.env` and runs the async loop |

---

## ⚙️ Configuration Reference

Every tunable value lives directly in the scripts. Where the two scripts differ, both values are shown.

| Setting | Value | Effect |
| :--- | :--- | :--- |
| **Required environment variables** | Query: `GOOGLE_API_KEY`, `PHOENIX_API_KEY`, `DATABASE_URL`, `CHROMA_API_KEY`. Chat: the same four plus `ASYNCPG_DATABASE_URL` | The script stops at startup if any of them is missing |
| **LLM** | `gemini/gemini-2.5-flash`, `temperature=0.3` | The model that writes the SQL and the answer, and its randomness |
| **LLM reliability** | `num_retries=2`, `fallbacks=["gemini/gemini-3.5-flash"]`, `drop_params=True` | Retries a failed call twice, then switches to the fallback model |
| **Embedding model** | `models/gemini-embedding-2`, `embed_batch_size=50` | Embeds the table schemas and each question |
| **Chunking** | Disabled | Each table description is embedded as one piece |
| **Retrieval depth** | `similarity_top_k=3` | Number of table schemas given to the LLM per question |
| **Table descriptions** | `table_context_dict` (only `dresses` is defined) | Hand-written context for each table. Other tables use the default |
| **Chroma collection** | Query: `sql_tables_query_schema`. Chat: `sql_table_chat_schema` | Where the table schema vectors are stored |
| **Phoenix project** | Query: `sql_retriever_query_project`. Chat: `sql_retriever_chat_project` | The project that receives the traces |
| **Phoenix endpoint** | `PHOENIX_COLLECTOR_ENDPOINT`, with a hardcoded default | Where traces are sent. The default points to the author's Phoenix space |
| **Chat memory** | `session_id="sql_table_chat_session"`, `token_limit=40000`, `table_name="sql_table_chat_memory"` | How the chat history is stored and trimmed (chat script only) |
| **Token counting** | `tiktoken` with `cl100k_base` | The tokenizer behind the token numbers |
| **Debug trace** | `LlamaDebugHandler(print_trace_on_end=True)` | Prints a trace in the terminal after each run |
| **Exit commands** | `exit`, `close`, `out`, `break`, `keluar`, `x` | Ends the session |

---

## 📚 Script Breakdown

### 1️⃣ `selected-schema-query.py`: single-turn NL-to-SQL

**Goal.** Answer one question at a time. Each question is independent, and nothing from earlier questions is carried over.

**What happens when you run it.**
1. Checks that the four required environment variables exist, and stops with a `ValueError` that names the missing ones.
2. Creates the token counter and the debug handler.
3. Configures the LLM and the embedding model.
4. Registers Phoenix tracing under the project `sql_retriever_query_project`.
5. Connects to ChromaDB Cloud and opens the `sql_tables_query_schema` collection.
6. Connects to PostgreSQL and prints every table it finds.
7. Builds one `SQLTableSchema` per table, using the hand-written description when one exists.
8. If the collection is empty, builds the `ObjectIndex` and stores it. Otherwise, loads the stored index.
9. Creates a `SQLTableRetrieverQueryEngine` that retrieves the top 3 schemas.
10. Starts the loop. After each answer it prints the SQL, the source nodes, the token usage, and the estimated cost, then resets the counters.

**Key code.**
```python
table_name_mapping = SQLTableNodeMapping(sql_database=sql_database)
table_schema_objs = [
    SQLTableSchema(table_name=table_name, context_str=table_context_dict.get(table_name))
    for table_name in available_tables
]

obj_index = ObjectIndex.from_objects(
    objects=table_schema_objs,
    object_mapping=table_name_mapping,
    index_cls=VectorStoreIndex,
    storage_context=storage_context
)

query_engine = SQLTableRetrieverQueryEngine(
    sql_database=sql_database,
    table_retriever=obj_index.as_retriever(similarity_top_k=3)
)
```

**Worth knowing.**
* A single question can trigger more than one LLM call (writing the SQL, then writing the answer). The cost shown is the sum of all of them.
* Empty input is rejected with a warning, and the loop continues.
* The SQL is read from `response.metadata["sql_query"]`.

### 2️⃣ `selected-schema-chat.py`: multi-turn NL-to-SQL with PostgreSQL memory

**Goal.** Keep a conversation, so a follow-up question can refer to the previous one.

**What happens when you run it.** Steps 1 to 9 are the same as in the query script, with these differences:
* It also requires `ASYNCPG_DATABASE_URL`.
* The Phoenix project is `sql_retriever_chat_project`.
* The schemas are stored in a separate collection, `sql_table_chat_schema`.
* It creates a `Memory` object and a `CondenseQuestionChatEngine`, and the loop calls `chat_engine.achat(...)`.

**Key code.**
```python
memory = Memory.from_defaults(
    session_id="sql_table_chat_session",
    token_limit=40000,
    async_database_uri=ASYNCPG_DATABASE_URL,
    table_name="sql_table_chat_memory"
)

chat_engine = CondenseQuestionChatEngine.from_defaults(
    query_engine=query_engine,
    llm=Settings.llm,
    memory=memory,
    verbose=True
)
```

**Worth knowing.**
* With `verbose=True`, the rewritten (condensed) question is printed, which shows how a follow-up was understood.
* The cost now also includes the LLM call that rewrites the question.
* The SQL is read from `response.sources[0].raw_output.metadata`.
* The memory uses a fixed `session_id`, so every run continues the same conversation.

### 🔬 Side-by-Side Comparison

| Aspect | `selected-schema-query.py` | `selected-schema-chat.py` |
| :--- | :--- | :--- |
| Mode | Single turn | Multi turn |
| Engine | `SQLTableRetrieverQueryEngine` | `CondenseQuestionChatEngine` around the same query engine |
| Call in the loop | `query_engine.aquery(...)` | `chat_engine.achat(...)` |
| Conversation memory | None | `Memory` stored in PostgreSQL (`sql_table_chat_memory`, 40000 token limit) |
| Chroma collection | `sql_tables_query_schema` | `sql_table_chat_schema` |
| Phoenix project | `sql_retriever_query_project` | `sql_retriever_chat_project` |
| Required variables | Four | Five, adding `ASYNCPG_DATABASE_URL` |
| Follow-up questions | Not understood | Rewritten into standalone questions using the history |

Everything else is shared: the models, `similarity_top_k=3`, the table descriptions, the token and cost reporting, and the error handling.

### 💡 Questions to Try

The sample table description is written for a `dresses` table, so these questions fit it.

| Question | What it shows |
| :--- | :--- |
| `How many dresses are recommended?` | A simple count. Check that the SQL uses the `Recommendation` flag correctly |
| `Show party dresses with a high price tier and a rating above 4.5` | `Price` is a tier and not a number, which the table context explains |
| `Which dresses have a floral pattern type?` | The SQL must quote the column as `"Pattern Type"` |
| `What is the average rating for each season?` | Grouping and averaging over a text column and a numeric column |
| Chat only: `How many dresses are for summer?`, then `And how many of those are recommended?` | The second question only makes sense with the first. Watch the condensed question that `verbose=True` prints |

---

## 🖥️ Example Console Output

An illustrative first-run session of the query script, based on the messages the script prints:

```text
⏳ [SYSTEM] Initializing LLM, Telemetry, and SQL Database connections...
⏳ [SYSTEM] Connecting to ChromaDB Cloud...
✅ [SYSTEM] Successfully connected to database. Found N tables.
🗄️  [DATABASE TABLES]:
   1. <table name>
⏳ [SYSTEM] Building new vector index for table schemas...

======================================================================
💬 [SYSTEM] NL-to-SQL Interactive Session Started. Type 'exit' to stop.
======================================================================

🗣️ [USER] You: <your question>
🧠 [AI] Translating query to SQL and fetching data...
----------------------------------------------------------------------
🤖 [AI RESPONSE]:
<the answer in natural language>

🔍 [GENERATED SQL QUERY]:
<the SQL that was executed>

📂 [SOURCE NODES RECOVERED]: <number of source nodes>
   ↳ Node 1 | Score: <score>
     Content: <the rows returned by the database>

📊 [LLAMAINDEX CALLBACK TOKEN OVERVIEW]:
Model Used        : <model>
Prompt Tokens     : <number>
Completion Tokens : <number>
Total LLM Tokens  : <number>
----------------------------------------------------------------------
💰 [COST ANALYSIS]:
Total Estimated Cost: $<amount> USD
======================================================================
```

On later runs, the build line is replaced by `⏳ [SYSTEM] Loading existing vector index for table schemas...`. The chat script prints the same blocks. It starts with `⏳ [SYSTEM] Initializing LLM, Telemetry, Database, and Chat Memory...` and asks `🧠 [AI] Condensing question context and fetching database records...` for every message.

---

## 📁 Repository Structure

```text
nl2sql-selected-schema-llamaindex/
├── selected-schema-query.py
├── selected-schema-chat.py
├── dresses.db
├── LICENSE
├── README.md
└── requirements.txt
```

| Path | Description |
| :--- | :--- |
| `selected-schema-query.py` | Single-turn NL-to-SQL with selected schema retrieval |
| `selected-schema-chat.py` | Multi-turn NL-to-SQL with PostgreSQL chat memory |
| [`dresses.db`](dresses.db) | The SQLite sample database used in this project, which holds the `dresses` table |
| `requirements.txt` | All Python dependencies, with notes inside the file |
| `LICENSE` | MIT License |
| `README.md` | You're reading it |

The sample database [`dresses.db`](dresses.db) is included, so you can try the scripts right away with the SQLite option. To query your own data, use a PostgreSQL database or a SQLite file that already contains the tables you want to query (see [Prepare the Database](#5-prepare-the-database)).

---

## 🏗️ Architecture & Data Flow

### 🔄 Query Script Flowchart

```mermaid
flowchart TD
    A["Tables found in PostgreSQL"] --> B["SQLTableSchema per table, with the hand-written context"]
    B --> C{"Is the Chroma collection empty?"}

    C -- "Yes" --> D
    C -- "No" --> G["Load the stored index with from_vector_store"]

    subgraph Indexing ["Runs only if the collection is empty"]
        D["GoogleGenAIEmbedding embeds each table schema"] --> E["ChromaDB Cloud collection of table schemas"]
    end

    E --> F["ObjectIndex"]
    G --> F

    Q["Question in the terminal"] --> R["Retriever returns the top 3 closest schemas"]
    F --> R
    R --> S["Gemini LLM writes SQL using only those schemas"]
    S --> T["The SQL runs on PostgreSQL"]
    T --> U["Gemini LLM turns the rows into a natural language answer"]
    U --> V["Answer, SQL, source nodes, tokens, and cost are printed"]
```

> **Note.** On every run, the script first checks whether the Chroma collection already has data. If it does, nothing is embedded again and the stored index is loaded. Phoenix records a trace for each run, and the token counter and debug handler observe every LLM call.

### 💬 What the Chat Script Adds

```mermaid
flowchart LR
    H["Chat history in PostgreSQL"] --> C["CondenseQuestionChatEngine"]
    N["New message, for example: only the summer ones"] --> C
    C --> S["Standalone question"]
    S --> E["SQLTableRetrieverQueryEngine, same flow as above"]
    E --> A["Answer"]
    A --> H
```

The new message and the history are combined into one standalone question. That question goes through the same retrieval and SQL generation shown above, and the exchange is saved back to the history.

---

## 🆚 Two Approaches to NL-to-SQL

LlamaIndex offers more than one query engine for NL-to-SQL. This repository implements the first approach below. A second repository implements `NLSQLTableQueryEngine`, and this section explains how the two differ.

### 📍 Where Each Approach Lives

| Approach | Query engine | Location |
| :--- | :--- | :--- |
| **Selected schema retrieval** | `SQLTableRetrieverQueryEngine` | This repository (`selected-schema-query.py` and `selected-schema-chat.py`) |
| **Fixed table list** | `NLSQLTableQueryEngine` | [nl2sql-all-schema-llamaindex](https://github.com/viochris/nl2sql-all-schema-llamaindex) |

### 🔍 What Differs

| Aspect | `SQLTableRetrieverQueryEngine` (this repo) | `NLSQLTableQueryEngine` (companion repo) |
| :--- | :--- | :--- |
| How tables reach the prompt | The question is matched against stored table schemas, and only the closest ones are used | The schema of the configured tables is placed in the prompt for every question |
| Who picks the tables | Similarity search, at question time | You, through the list of tables |
| Needs a vector database | Yes, ChromaDB Cloud stores the schema embeddings | No |
| Needs an embedding model | Yes, `models/gemini-embedding-2` | No |
| Extra call per question | One embedding call for the question | None |
| Extra setup | An `ObjectIndex`, a node mapping, and a collection to build and keep in sync | None beyond `SQLDatabase` and the table list |
| Prompt size as tables grow | Stays small, because only the top 3 schemas are included | Grows with the number of tables included |
| Best suited for | Databases with many tables | Databases with few tables |
| Typical failure | The right table is not retrieved, so the SQL cannot be correct | The prompt becomes long or noisy when many tables are included |
| Moving parts | More | Fewer |

The matching implementation of `NLSQLTableQueryEngine` is in the repository linked in the table above.

### 🧭 Which One Fits Your Case

* If your database has a handful of tables, a fixed table list is simpler and has fewer things that can go wrong.
* If your database has many tables, or the table descriptions are long, selecting the schemas for each question keeps the prompt small. That is what this repository demonstrates.
* In this repository the sample describes one table, so the retrieval step always returns it. The selection only has an effect once more tables are added.

---

## 💻 Installation & Reproduction Steps

### 📋 Prerequisites
* **Python 3.10 or newer** is required.
* **Accounts and keys** you will need: a Google AI Studio API key for Gemini (LLM and embeddings), a [Chroma Cloud](https://www.trychroma.com/) API key, and an [Arize Phoenix](https://phoenix.arize.com/) API key.
* **A PostgreSQL database** that contains the tables to query. The chat script also uses it to store the conversation history. A hosted database, for example one on Supabase, works with its connection string.
* **Internet access**, because the scripts call Gemini, ChromaDB Cloud, and Phoenix.

### 🛠️ CLI Installation & Execution

#### 1. Clone the Repository
```bash
git clone https://github.com/viochris/nl2sql-selected-schema-llamaindex.git
cd nl2sql-selected-schema-llamaindex
```

#### 2. Create and Activate a Virtual Environment
```bash
# macOS/Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

#### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
> The LlamaIndex ecosystem ships as many small, fast-moving sub-packages. If you hit a resolver conflict, try installing into a clean virtual environment and letting `pip` resolve every package from `requirements.txt` in a single command rather than one at a time, since that gives it the full picture needed to pick mutually compatible versions.

#### 4. Configure Environment Variables
Create a `.env` file in the project root.
```env
GOOGLE_API_KEY=your_google_ai_studio_key
CHROMA_API_KEY=your_chroma_cloud_key
PHOENIX_API_KEY=your_phoenix_key
PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com/s/your-space/v1/traces
# DATABASE_URL has two options. Keep only one of them active.
# Option 1: PostgreSQL, a database server
DATABASE_URL=postgresql://user:password@host:5432/dbname
# Option 2: SQLite, a local database file
# DATABASE_URL=sqlite:///dresses.db
ASYNCPG_DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

| Variable | Used by | Purpose |
| :--- | :--- | :--- |
| `GOOGLE_API_KEY` | Both | Gemini key. The embedding model receives it directly, and LiteLLM finds its Gemini key in the environment for the LLM calls |
| `CHROMA_API_KEY` | Both | Connects to ChromaDB Cloud |
| `PHOENIX_API_KEY` | Both | Authenticates the trace upload to Phoenix |
| `DATABASE_URL` | Both | SQLAlchemy connection string of the database that is queried |
| `ASYNCPG_DATABASE_URL` | Chat only | Async connection string for the chat memory table |
| `PHOENIX_COLLECTOR_ENDPOINT` | Both, optional | Where traces are sent |

> The scripts have a default value for `PHOENIX_COLLECTOR_ENDPOINT` that points to the author's own Phoenix space. Set this variable to your own space, otherwise your traces will not appear in your account.
>
> Keep `.env` out of version control.

**Choosing `DATABASE_URL`: PostgreSQL or SQLite**

`DATABASE_URL` accepts any SQLAlchemy connection string, so the database that is queried can be either of these two. Use one line only.

| Aspect | PostgreSQL | SQLite |
| :--- | :--- | :--- |
| Example | `postgresql://user:password@host:5432/dbname` | `sqlite:///dresses.db` |
| What it is | A database server, which can run locally or be hosted (for example on Supabase) | A single file on your disk, with no server |
| Setup | You need a running server and its credentials | Nothing to install, because SQLite is built into Python |
| Extra driver | `psycopg2-binary` (already in `requirements.txt`) | None |
| Access | Reachable from other machines with the credentials | Only the machine that has the file |
| Best suited for | A shared or hosted database, and larger data | Local testing and small datasets such as the `dresses` sample |

A few details to keep in mind:
* In `sqlite:///dresses.db`, the path is relative to the folder where you run the script. For an absolute path, use four slashes, for example `sqlite:////home/user/data/dresses.db`.
* With SQLite, the file must already contain your tables. The scripts do not create them. The included [`dresses.db`](dresses.db) already has the `dresses` table, so `DATABASE_URL=sqlite:///dresses.db` works as it is when you run the scripts from the project root.
* `selected-schema-chat.py` still needs `ASYNCPG_DATABASE_URL`, which must point to a PostgreSQL database, because the chat history is stored there. SQLite replaces `DATABASE_URL` only. It does not replace the chat memory database.
* The Chroma collection stores the table schemas of whichever database was used when it was built. If you switch `DATABASE_URL` to a different database, delete the collection as shown in step 7.

#### 5. Prepare the Database
The scripts read the table list from the database when they start, so the tables must already exist. This project uses the SQLite database [`dresses.db`](dresses.db), which is included in the repository. The sample description in the code is written for its table named `dresses` with 14 columns: `Dress_ID`, `Style`, `Price`, `Rating`, `Size`, `Season`, `NeckLine`, `SleeveLength`, `waiseline`, `Material`, `FabricType`, `Decoration`, `Pattern Type`, and `Recommendation`.

To describe your own tables, add an entry to `table_context_dict` in each script. The key must match the table name exactly.
```python
table_context_dict = {
    "your_table": """
    Table 'your_table': what the table holds, in one or two sentences.

    Columns:
    - column_a (TEXT): what it means, and the exact values it can have.
    - column_b (INTEGER): what it means.
    """
}
```
A table without an entry still works, but it is described only by the auto-generated schema information.

> Use a database user that can only read. The generated SQL is executed as it is, so a read-only user is the safest way to make sure a bad query cannot change your data.

#### 6. Run the Scripts
```bash
# single turn
python selected-schema-query.py

# multi turn with PostgreSQL memory
python selected-schema-chat.py
```
Type your questions at the `🗣️ [USER] You:` prompt. Type `exit`, `close`, `out`, `break`, `keluar`, or `x` to end the session.

#### 7. Rebuild the Schema Index After Changes
The index is built only when the Chroma collection is empty. If you add a table or edit a table description, the stored index does not change on its own. Delete the collection once, and the next run builds it again.
```python
import os
import chromadb
from dotenv import load_dotenv

load_dotenv()
client = chromadb.CloudClient(api_key=os.getenv("CHROMA_API_KEY"))
client.delete_collection("sql_tables_query_schema")   # query script
client.delete_collection("sql_table_chat_schema")     # chat script
```

---

## 🛠️ Troubleshooting & Error Messages

### 🚨 Error Categories Printed by the Scripts

When something fails during setup or inside the loop, both scripts print the traceback and then one of these summaries, and exit with code 1. The checks run from top to bottom, and the first match is used.

| Message prefix | Matches when |
| :--- | :--- |
| `🚨 [DATABASE ERROR]` | The error type is `OperationalError`, `DatabaseError`, or `ProgrammingError`, or the message contains `sql` or `connection` |
| `🚨 [API QUOTA ERROR]` | The error type is `RateLimitError` or `ResourceExhausted`, or the message contains `quota` or `429` |
| `🚨 [AUTH ERROR]` | The error type is `AuthenticationError` or `PermissionError`, or the message contains `api_key` or `unauthorized` |
| `🚨 [NETWORK ERROR]` | The error type is `TimeoutError`, `ConnectTimeout`, or `APITimeoutError`, or the message contains `timeout` |
| `🚨 [PROCESSING ERROR]` | The error type is `ValueError`, `TypeError`, or `IndexError`, or the message contains `pipeline` or `node` |
| `🚨 [UNKNOWN CRITICAL ERROR]` | Anything that does not match the categories above |

### 🧰 Common Problems

| Symptom | Likely cause | What to do |
| :--- | :--- | :--- |
| `Missing required environment variables: ...` at startup | A variable is missing from `.env` | Add the variables named in the message. The chat script also needs `ASYNCPG_DATABASE_URL` |
| LiteLLM reports a missing Gemini key | LiteLLM did not find the key in the environment | Also set `GEMINI_API_KEY` in `.env` with the same value as `GOOGLE_API_KEY` |
| Traces do not show up in your Phoenix account | `PHOENIX_COLLECTOR_ENDPOINT` still points to the default space | Set it to your own Phoenix endpoint |
| The SQL ignores a new table or a new description | The stored index in Chroma is reused | Delete the collection as shown in step 7 |
| The SQL uses wrong column names or values | The table has no hand-written description, or it is incomplete | Add or refine the entry in `table_context_dict`, then rebuild the index |
| Error about the async driver in the chat script | `asyncpg` is not installed, or `ASYNCPG_DATABASE_URL` does not start with `postgresql+asyncpg://` | Run `pip install -r requirements.txt` and check the URL |
| The chat remembers an old conversation | The memory uses a fixed `session_id` | Change `session_id` in the script, or clear the `sql_table_chat_memory` table |
| Long trace output appears after each answer | `LlamaDebugHandler` is created with `print_trace_on_end=True` | Set it to `False` in the script |
| A database error appears for a problem that is not about the database | Any message containing `sql` or `connection` is reported as a database error | Read the printed traceback to find the real cause |

---

## 📝 Conclusion

This project set out to solve five problems: prompts that grow with every table, schemas that carry no meaning, questions that have no context, history that disappears, and runs that are hard to inspect. The two scripts address them directly. Table descriptions are written by hand, embedded once, and stored in ChromaDB, so each question brings only the closest few schemas to the LLM. The query script handles one question at a time. The chat script adds a step that rewrites follow-ups and keeps its history in PostgreSQL. Phoenix tracing, token counting, and cost estimates make every run visible.

A few design choices are worth pointing out. Building the index only when the collection is empty avoids paying for the same embeddings twice. Every answer is printed together with its SQL and the rows behind it, so it can be checked. Keeping each script in a single readable file makes it easy to follow, run, and modify.

It is also not a finished product. Only one table has a hand-written description, the stored index does not refresh when tables change, and the generated SQL is run without a safety check. The sections below go through these gaps and lay out the next steps.

---

## ⚠️ System Limitations

### 🏗️ Architectural Limitations
* **The index is not refreshed automatically.** The schema index is built only when the Chroma collection is empty. Changes to tables or descriptions are not picked up until the collection is deleted.
* **The generated SQL is executed directly.** Nothing blocks statements that change data, so protection depends on the permissions of the database user.
* **One failed question ends the session.** The loop runs inside the main error handler, so any exception stops the script with exit code 1 instead of letting you retry.
* **Settings are hardcoded.** Collection names, Phoenix project names, model names, `similarity_top_k`, and the memory session id are fixed values in the scripts.
* **A fixed conversation in the chat script.** The memory uses one `session_id` and one table name, so every run continues the same conversation.
* **Only tables in the default schema are listed.** The scripts use SQLAlchemy's table list, which leaves out views and tables in other schemas.
* **The memory table can appear in the table list.** If `DATABASE_URL` and `ASYNCPG_DATABASE_URL` point to the same database, the chat memory table is a normal table there. The next time the index is built, it can be indexed like any other table.
* **Startup validation checks presence only.** The scripts confirm that each variable is set, but not that its value is valid.
* **Dependence on external services.** The scripts need live access to Gemini, ChromaDB Cloud, Phoenix, and PostgreSQL. There is no offline mode.
* **CLI-only interface.** All interaction happens in a terminal. There is no web page and no visual history.

### 🔬 Model & Domain Limitations
* **Only one table has a hand-written description.** `table_context_dict` contains `dresses` only. Other tables fall back to the default schema information, which can lead to less accurate SQL.
* **Retrieval has no effect with one table.** With a single described table, `similarity_top_k=3` can only return that table. The selection becomes meaningful when the database has several tables.
* **A retrieval miss means wrong SQL.** Only the top 3 schemas reach the LLM. If the right table is not among them, the SQL cannot be correct.
* **The SQL can still be wrong.** The LLM may write a query that runs but does not answer the question. The correctness of the generated SQL was not measured against a labeled question set.
* **Follow-ups depend on the rewrite.** In the chat script, a follow-up is rewritten by the LLM, so an unclear message can be misread.
* **Token counts are approximate.** `TokenCountingHandler` uses the `cl100k_base` tokenizer from OpenAI, while the model is Gemini.
* **The cost covers LLM calls only.** Embedding calls are not included, and the estimate depends on the response data that LiteLLM receives.
* **The fallback model can change the answer.** If the primary model fails, the fallback model answers, and its output may differ in style and quality.

---

## 🚀 Future Work
* **Describe more tables.** Write hand-written descriptions for several tables, so the schema retrieval is exercised properly.
* **Refresh the index when tables change.** Detect changes in the table list or descriptions and rebuild the collection automatically.
* **Block unsafe SQL.** Reject any generated statement that is not a read query before it is executed.
* **Choose which tables are indexed.** Take an include list from configuration, so helper tables such as the memory table stay out of the index.
* **Make the chat loop resilient.** Move error handling inside the loop, so a failed turn prints the error and lets you try again.
* **Move configuration out of the code.** Take collection names, model names, `similarity_top_k`, and the session id from environment variables or command-line arguments.
* **Evaluate the SQL quality.** Build a small labeled set of questions with expected results, and measure how often the generated SQL is correct.
* **Add a simple interface.** A small web interface would make answers, SQL, and sources easier to read than terminal output.

---

## 📄 License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---
**Author:** [Silvio Christian, Joe](https://github.com/viochris)

*"Ask in plain language, retrieve only the schemas that matter."*
