# core/application/services/openai_service/common_service.py
from typing import Callable, Optional
from core.application.services.openai_service.service_logic import OpenAIService
from infrastructure.repositories.retrieval_service import RetrievalService
from core.domain.models.classifier_models import QueryIntent
from helpers.utils import GreetingUtils
import pyodbc
from fastapi.concurrency import run_in_threadpool
import pyodbc
import os


class RAGService:

    def __init__(self):
        self.ai = OpenAIService()
        self.retrieval = RetrievalService()

    async def handle(self, email: str, query: str, threadid: Optional[str], get_db_connection: Callable[[], pyodbc.Connection]):

        # 1. Greeting detection
        if GreetingUtils.is_greeting(query):
            return ("Hello! How can I help you today?", QueryIntent.CASUAL)

        # 2. Rewrite query
        rewritten_query = await self.ai.rewrite(query)
        print("\n REWRITTEN QUERY:", rewritten_query)

        # 3. Classify rewritten query
        intent = await self.ai.classify(rewritten_query)

        if intent == QueryIntent.CASUAL:
            return ("I only answer policy or service related queries.", QueryIntent.CASUAL)

        if intent == QueryIntent.INVALID:
            return ("Sorry, this question is not covered in the available documents.", intent)

        # 4. User Intent via LLM → (first guess only)
        user_intent = await self.ai.extract_intent(rewritten_query)
        print("USER INTENT (LLM):", user_intent)

        # 5. Embed rewritten query
        embedding = await self.ai.embed(rewritten_query)

        # 6. SEARCH TO DETECT REAL FUNCTIONS (unfiltered vector search)
        unfiltered_chunks, functions_found = await self.retrieval.detect_ambiguity(
            rewritten_query, embedding
        )
        print("FUNCTIONS FOUND (METADATA):", functions_found)

        # 7. REAL ambiguity detection (metadata-based)
        if len(functions_found) > 1:
            msg = (
                "This query exists under multiple functions: "
                + ", ".join(functions_found)
                + ". Please specify one."
            )
            return (msg, QueryIntent.CASUAL)

        # 8. CLEAR case → only 1 function
        function_filter = None
        if len(functions_found) == 1:
            function_filter = functions_found[0]
        else:
            # fallback to LLM intent if metadata has only 0 results
            function_filter = user_intent.get("function")

        print("FINAL FUNCTION FILTER:", function_filter)

        # 9. FILTERED retrieval
        print("[LOG] Calling retrieval with filter:")
        chunks = await self.retrieval.retrieve(
            rewritten_query,
            embedding,
            function=function_filter
        )

        ###
        

        # def get_conn():
        #     conn_str = (
        #         f"Driver={{{os.getenv('DRIVER')}}};"
        #         f"Server={os.getenv('SERVER')};"
        #         f"Database={os.getenv('DATABASE')};"
        #         f"Trusted_Connection={os.getenv('TRUSTED_CONNECTION')};"
        #         f"TrustServerCertificate={os.getenv('TRUSTSERVERCERTIFICATE')};"
        #     )
        #     return pyodbc.connect(conn_str)

        async def get_last_5_entries_by_email(email: str):
            def _query():
                
                query = """
                SELECT TOP 5 *
                FROM dbo.ChatMessages
                WHERE CreatedBy = ?
                ORDER BY CreatedAt DESC
                """
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(query, (email,))

                columns = [col[0] for col in cur.description]
                rows = cur.fetchall()

                conn.close()

                return [dict(zip(columns, row)) for row in rows]

            return await run_in_threadpool(_query)
        
        memory_value = await get_last_5_entries_by_email(email)
        print("[LOG]-----last 5 entries for email:", email)
        print(memory_value)
        ###
        if not chunks:
            return ("I couldn’t find this in the available policy documents.", intent)

        return (chunks, QueryIntent.VALID)