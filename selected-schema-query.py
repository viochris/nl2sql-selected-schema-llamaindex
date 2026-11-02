# ==============================================================================
# 0. REQUIRED LIBRARIES & DEPENDENCIES
# ==============================================================================
# Standard library imports for system operations, logging, and asynchronous execution
import os
import sys
import logging
import traceback
import asyncio

# Third-party utility libraries for environment management, tokenization, and API interaction
import chromadb
import nest_asyncio
import litellm
import tiktoken
from dotenv import load_dotenv

# SQLAlchemy components for database connection and inspection
from sqlalchemy import create_engine, inspect

# LlamaIndex core components for vector storage and application context
from llama_index.core import (
    Settings,
    VectorStoreIndex,
    StorageContext,
    SQLDatabase
)
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler, LlamaDebugHandler
from llama_index.core.callbacks.schema import EventPayload

# ARCHITECTURE NOTE: Chunking is bypassed since 1 schema = 1 embed, making splitting unnecessary.
# from llama_index.core.node_parser import SentenceSplitter

# LlamaIndex SQL and Object components for schema mapping and retrieval
from llama_index.core.objects import SQLTableNodeMapping, ObjectIndex, SQLTableSchema
from llama_index.core.indices.struct_store import SQLTableRetrieverQueryEngine

# LlamaIndex integrations for specific external services (ChromaDB, Google GenAI, LiteLLM)
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.google_genai import GoogleGenAIEmbedding
from llama_index.llms.litellm import LiteLLM

# Phoenix OpenTelemetry instrumentation for distributed tracing and performance observability
from phoenix.otel import register
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor


# ==============================================================================
# 1. SYSTEM INITIALIZATION & TELEMETRY CONFIGURATION
# ==============================================================================
# Apply nested asyncio for compatibility with CLI and Jupyter environments
nest_asyncio.apply()

# Configure root and specific module logging levels to suppress unnecessary warnings
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)

# Load environment variables from the .env file
load_dotenv()

# Extract required API keys and connection strings
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
PHOENIX_API_KEY = os.getenv("PHOENIX_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
CHROMA_API_KEY = os.getenv("CHROMA_API_KEY")

# Validate all critical environment variables before proceeding
if not all([GOOGLE_API_KEY, PHOENIX_API_KEY, DATABASE_URL, CHROMA_API_KEY]):
    missing_keys = []
    if not GOOGLE_API_KEY: missing_keys.append("GOOGLE_API_KEY")
    if not PHOENIX_API_KEY: missing_keys.append("PHOENIX_API_KEY")
    if not DATABASE_URL: missing_keys.append("DATABASE_URL")
    if not CHROMA_API_KEY: missing_keys.append("CHROMA_API_KEY")

    raise ValueError(f"🚨 [SYSTEM ERROR] Missing required environment variables: {', '.join(missing_keys)}")

# Inject Phoenix telemetry headers for tracing authentication and routing
os.environ["PHOENIX_CLIENT_HEADERS"] = f"api_key={PHOENIX_API_KEY}"
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "https://app.phoenix.arize.com/s/viochristian12/v1/traces")


# ------------------------------------------------------------------------------
# GLOBAL EXECUTION ZONE: Core components initialization and interactive query loop
# ------------------------------------------------------------------------------
try:
    print("⏳ [SYSTEM] Initializing LLM, Telemetry, and SQL Database connections...")

    # Initialize token counting handler with OpenAI's tiktoken encoder for cost tracking
    token_counter = TokenCountingHandler(
        tokenizer=tiktoken.get_encoding("cl100k_base").encode,
        verbose=False
    )

    # Initialize debug handler to trace LLM inputs, outputs, and intermediate states
    debug_handler = LlamaDebugHandler(print_trace_on_end=True)

    # Configure the global LiteLLM model with fallback mechanisms and strict parameters
    Settings.llm = LiteLLM(
        model="gemini/gemini-2.5-flash",
        temperature=0.3,
        additional_kwargs={
            "fallbacks": ["gemini/gemini-3.5-flash"],
            "drop_params": True,
            "num_retries": 2 
        }
    )

    # Configure the embedding model required for mapping and retrieving SQL schemas
    Settings.embed_model = GoogleGenAIEmbedding(
        model_name="models/gemini-embedding-2", 
        api_key=GOOGLE_API_KEY, 
        embed_batch_size=50
    )
    
    # ARCHITECTURE NOTE: Chunking is disabled here. Even though embedding is used, 
    # it is mapped one-to-one (1 schema = 1 embedding), making splitting unnecessary.
    # Settings.node_parser = SentenceSplitter(
    #     chunk_size=2048,
    #     chunk_overlap=200
    # )

    # Register handlers into the global callback manager
    Settings.callback_manager = CallbackManager([token_counter, debug_handler])

    # Register OpenTelemetry tracer provider for Phoenix observability
    tracer_provider = register(
        project_name="sql_retriever_query_project",
        auto_instrument=True
    )

    # Instrument LlamaIndex with the configured tracer provider
    LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)

    # Initialize ChromaDB client and collection for vector storage of table schemas
    print("⏳ [SYSTEM] Connecting to ChromaDB Cloud...")
    chroma_client = chromadb.CloudClient(api_key=CHROMA_API_KEY)
    chroma_collection = chroma_client.get_or_create_collection("sql_tables_query_schema")

    # Set up VectorStore and StorageContext with Chroma as the backend
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Establish connection to the SQL database using SQLAlchemy
    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    available_tables = inspector.get_table_names()

    print(f"✅ [SYSTEM] Successfully connected to database. Found {len(available_tables)} tables.")
    print("🗄️  [DATABASE TABLES]:")
    
    # Iteratively display available tables in a structured format
    for idx, table_name in enumerate(available_tables, 1):
        print(f"   {idx}. {table_name}")

    # Wrap the SQLAlchemy engine into a LlamaIndex SQLDatabase object
    sql_database = SQLDatabase(
        engine=engine,
        include_tables=available_tables
    )

    # Custom table schema descriptions to override auto-generated database schemas.
    # This guarantees the LLM receives precise column context and formatting rules.
    table_context_dict = {
        "dresses": """
        Table 'dresses': a catalog of 500 women's dress products, each described by 14 attributes covering style, pricing, physical design, and material. All text/categorical columns use lowercase values (not capitalized, not Title Case) unless noted otherwise. Missing/unknown values are stored as NULL.

        Columns:
        - Dress_ID (INTEGER): Unique identifier for each dress.
        - Style (TEXT): The overall fashion style category. Lowercase values, e.g. 'casual', 'party', 'sexy', 'vintage', 'brief', 'cute', 'bohemian', 'novelty', 'flare', 'work', 'ol', 'fashion'.
        - Price (TEXT): Price tier as a category, NOT a numeric amount. Lowercase values: 'low', 'average', 'high', 'very-high'. Can be NULL.
        - Rating (REAL): Average customer rating on a 0.0–5.0 scale (e.g. 4.5, 3.6). A rating of 0.0 usually means the item has no reviews yet.
        - Size (TEXT): Garment size. Lowercase values: 's', 'm', 'l', 'xl', 'free' (free size).
        - Season (TEXT): The season the dress is suited for. Lowercase values: 'summer', 'autumn', 'spring', 'winter'. Can be NULL.
        - NeckLine (TEXT): Neckline/collar design. Lowercase, hyphenated values, e.g. 'o-neck', 'v-neck', 'boat-neck', 'square-collar', 'halter', 'backless', 'sweetheart'. Can be NULL.
        - SleeveLength (TEXT): Sleeve length style. Lowercase, hyphenated values, e.g. 'sleeveless', 'short', 'full', 'half-sleeve', 'three-quarter', 'cap-sleeves', 'butterfly-sleeve'. Can be NULL.
        - waiseline (TEXT): Waistline design (note: column name is misspelled "waiseline", not "waistline" — use this exact spelling in SQL). Lowercase values: 'empire', 'natural', 'dropped', 'princess'. Can be NULL.
        - Material (TEXT): Primary fabric material. Lowercase values, e.g. 'cotton', 'polyester', 'silk', 'chiffon', 'lace', 'linen', 'spandex', 'other'. Can be NULL.
        - FabricType (TEXT): Fabric weave/construction type. Lowercase values, e.g. 'chiffon', 'satin', 'jersey', 'lace', 'knitting', 'organza', 'corduroy'. Can be NULL.
        - Decoration (TEXT): Decorative embellishment on the dress. Lowercase values, e.g. 'ruffles', 'embroidery', 'lace', 'beading', 'sequined', 'bow', 'pockets'. Can be NULL.
        - Pattern Type (TEXT): Print/pattern design (note: column name contains a space — must be quoted in SQL, e.g. "Pattern Type"). Lowercase values, e.g. 'solid', 'print', 'floral', 'striped', 'dot', 'animal', 'geometric', 'plaid', 'none'. Can be NULL.
        - Recommendation (INTEGER): Binary flag indicating whether the dress is recommended. 1 = recommended, 0 = not recommended.
        """
    }

    # Map SQL tables to Node structures for the ObjectIndex
    table_name_mapping = SQLTableNodeMapping(sql_database=sql_database)
    table_schema_objs = [
        SQLTableSchema(
            table_name=table_name,
            context_str=table_context_dict.get(table_name)
        )
        for table_name in available_tables
    ]

    # Initialize or load the ObjectIndex depending on Chroma collection state
    if chroma_collection.count() == 0:
        print("⏳ [SYSTEM] Building new vector index for table schemas...")
        obj_index = ObjectIndex.from_objects(
            objects=table_schema_objs,
            object_mapping=table_name_mapping,
            index_cls=VectorStoreIndex,
            storage_context=storage_context
        )
    else:
        print("⏳ [SYSTEM] Loading existing vector index for table schemas...")
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        obj_index = ObjectIndex(index=index, object_node_mapping=table_name_mapping)

    # Initialize the query engine that retrieves schemas via vector search before SQL generation
    query_engine = SQLTableRetrieverQueryEngine(
        sql_database=sql_database,
        table_retriever=obj_index.as_retriever(similarity_top_k=3)
    )

    # --------------------------------------------------------------------------
    # ASYNCHRONOUS INTERACTIVE LOOP
    # Defines the main coroutine to process user inputs and fetch database responses
    # --------------------------------------------------------------------------
    async def main():
        # Purge any residual tokens or events prior to starting the interactive loop
        token_counter.reset_counts()
        debug_handler.flush_event_logs()

        print("\n" + "="*70)
        print("💬 [SYSTEM] NL-to-SQL Interactive Session Started. Type 'exit' to stop.")
        print("="*70)

        while True:
            # Capture natural language query from the user
            user_query = input("\n🗣️ [USER] You: ").strip()

            # Guard Clause: Handle empty inputs directly
            if not user_query:
                print("⚠️ [SYSTEM WARNING] Input cannot be empty. Please ask a valid question.")
                continue

            # Guard Clause: Handle termination commands
            if user_query.lower() in ["exit", "close", "out", "break", "keluar", "x"]:
                print("🛑 [SYSTEM] Terminating database session. Goodbye!")
                break

            print("🧠 [AI] Translating query to SQL and fetching data...")
            response = await query_engine.aquery(user_query)

            # Initialize tracking variables for token cost metrics
            total_cost = 0.0
            model_used = "Unknown"

            # Extract LLM event payloads to calculate precise execution costs
            llm_events = debug_handler.get_llm_inputs_outputs()
            for start_event, end_event in llm_events:
                response_obj = end_event.payload.get(EventPayload.RESPONSE)
                if response_obj is not None and getattr(response_obj, "raw", None):
                    response_raw = response_obj.raw
                    total_cost += litellm.completion_cost(completion_response=response_raw)
                    model_used = response_raw.get("model", "Unknown")

            # Fallback validation in case the query engine returns None
            if not response:
                print("⚠️ [SYSTEM WARNING] The query engine failed to generate a response.")
                continue

            # Display the synthesized natural language response
            print("-" * 70)
            print("🤖 [AI RESPONSE]:")
            print(response)

            # Display the raw SQL query synthesized by the LLM
            print("\n🔍 [GENERATED SQL QUERY]:")
            print(response.metadata.get("sql_query", "No SQL Query was generated."))

            # Iterate through source nodes to display retrieved context and raw data
            source_nodes = response.source_nodes
            print(f"\n📂 [SOURCE NODES RECOVERED]: {len(source_nodes)}")
            for i, node in enumerate(source_nodes, 1):
                print(f"   ↳ Node {i} | Score: {node.score}")
                print(f"     Content: {node.get_content().strip()}")

            # Token usage and cost analysis display
            print(f"\n📊 [LLAMAINDEX CALLBACK TOKEN OVERVIEW]:")
            print(f"Model Used        : {model_used}")
            print(f"Prompt Tokens     : {token_counter.prompt_llm_token_count}")
            print(f"Completion Tokens : {token_counter.completion_llm_token_count}")
            print(f"Total LLM Tokens  : {token_counter.total_llm_token_count}")
            print("-" * 70)
            print(f"💰 [COST ANALYSIS]:")
            print(f"Total Estimated Cost: ${total_cost:g} USD")
            print("=" * 70)

            # Flush trackers to ensure the next iteration starts fresh
            token_counter.reset_counts()
            debug_handler.flush_event_logs()

    # Execute the main asynchronous loop when the script is run directly
    if __name__ == "__main__":
        asyncio.run(main())

# ==============================================================================
# 2. COMPREHENSIVE EXCEPTION HANDLING & ERROR ROUTING
# ==============================================================================
except Exception as e:
    error_type = type(e).__name__
    error_msg = str(e).lower()
    error_raw = str(e)

    print("\n" + "="*70)
    print("💥 [CRITICAL FAILURE] NL-to-SQL engine execution aborted!")
    print("="*70)
    
    print("🔍 [TRACEBACK LOG]:")
    traceback.print_exc()
    print("-" * 70)

    print("📌 [ERROR DIAGNOSTICS SUMMARY]:")
    
    # Handle database connection and SQL parsing failures
    if error_type in ["OperationalError", "DatabaseError", "ProgrammingError"] or "sql" in error_msg or "connection" in error_msg:
        print(f"🚨 [DATABASE ERROR] {error_type}: Database connection failed or SQL execution error. Details: {error_raw}")
        
    # Handle API quotas and rate limits from LiteLLM/Gemini
    elif error_type in ["RateLimitError", "ResourceExhausted"] or "quota" in error_msg or "429" in error_msg:
        print(f"🚨 [API QUOTA ERROR] {error_type}: Rate limit exceeded or API quota exhausted. Details: {error_raw}")
        
    # Handle invalid API credentials
    elif error_type in ["AuthenticationError", "PermissionError"] or "api_key" in error_msg or "unauthorized" in error_msg:
        print(f"🚨 [AUTH ERROR] {error_type}: Authentication failure or access denied. Details: {error_raw}")

    # Handle network timeouts
    elif error_type in ["TimeoutError", "ConnectTimeout", "APITimeoutError"] or "timeout" in error_msg:
        print(f"🚨 [NETWORK ERROR] {error_type}: The AI model or database took too long to respond. Details: {error_raw}")

    # Handle structural or internal pipeline processing errors
    elif error_type in ["ValueError", "TypeError", "IndexError"] or "pipeline" in error_msg or "node" in error_msg:
        print(f"🚨 [PROCESSING ERROR] {error_type}: Invalid data structure or pipeline processing failure. Details: {error_raw}")
        
    # Default fallback
    else:
        print(f"🚨 [UNKNOWN CRITICAL ERROR] {error_type}: An unexpected exception occurred. Details: {error_raw}")
        
    print("="*70 + "\n")
    
    # Terminate the OS process cleanly
    sys.exit(1)