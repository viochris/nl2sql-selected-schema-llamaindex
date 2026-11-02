# nl2sql-selected-schema-llamaindex
Natural language to SQL with LlamaIndex that retrieves only the table schemas relevant to each question from ChromaDB using Gemini embeddings, then generates and runs the SQL. Includes a single-turn query script and a multi-turn chat script with PostgreSQL memory for follow-up questions, plus Phoenix tracing, token counting, and cost tracking.
