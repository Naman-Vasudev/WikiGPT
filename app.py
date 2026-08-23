import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import wikipedia
from google import genai
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Load environment variables from .env
load_dotenv()

# Set custom user agent for Wikipedia API queries to prevent blocking/rate-limiting
# Using a unique policy-compliant header based on the Render deployment hostname
render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
wikipedia.set_user_agent(f"WikiGPT/1.0 (https://{render_host}; contact@example.com)")

# Initialize FastAPI
app = FastAPI(title="WikiGPT API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request schema
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []

def get_wikipedia_content(query, max_results=3):
    try:
        # Search wikipedia for the query with retries
        import time
        search_results = []
        for attempt in range(3):
            try:
                search_results = wikipedia.search(query, results=max_results)
                break
            except Exception:
                if attempt == 2:
                    return [], "Wikipedia API is temporarily rate-limiting this server. Please try again in a few seconds."
                time.sleep(1.5)

        if not search_results:
            return [], f"No Wikipedia articles found for '{query}'."

        all_content = []
        processed_pages = []

        for result in search_results:
            try:
                page = wikipedia.page(result, auto_suggest=False)

                if page.title in processed_pages:
                    continue
                
                processed_pages.append(page.title)

                page_info = {
                    "title": page.title,
                    "url": page.url,
                    "content": page.content,
                    "summary": page.summary
                }
                all_content.append(page_info)

            except Exception:
                # Catch any disambiguation, decoding, or page errors and try the next result
                continue

        return all_content, None

    except Exception as e:
        return [], f"Error retrieving Wikipedia content: {str(e)}"

def create_vector_store(articles, api_key):
    splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=300)
    chunks, metadatas = [], []

    for article in articles:
        article_chunks = splitter.split_text(article["content"])
        for chunk in article_chunks:
            chunks.append(chunk)
            metadatas.append({
                "source": article["title"],
                "url": article["url"]
            })

    # Use Google's active embedding model models/gemini-embedding-001
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001", 
        google_api_key=api_key
    )
    vector_store = FAISS.from_texts(chunks, embeddings, metadatas=metadatas)

    return vector_store

def format_citations(similar_docs, articles):
    citations = []
    context = ""

    for doc in similar_docs:
        context += doc.page_content + " "
        source = doc.metadata.get("source", "Unknown Source")

        article_url = next((article["url"] for article in articles if article["title"] == source), None)

        if article_url:
            citations.append(f"{source}|{article_url}")
        else:
            citations.append(f"{source}|")

    # De-duplicate citations
    citations = list(dict.fromkeys(citations))
    return context.strip(), citations

def get_answer(search_query, original_query, vector_store, articles, api_key, history=[]):
    similar_docs = vector_store.similarity_search(search_query, k=3)
    context, citations = format_citations(similar_docs, articles)

    # Format history context for the prompt
    history_context = ""
    if history:
        history_context = "Conversation History:\n" + "\n".join([f"{msg.role}: {msg.content}" for msg in history]) + "\n\n"

    prompt = f"""You are WikiGPT, a helpful assistant that provides precise information based on Wikipedia articles.
Answer the user's question, keeping the conversation history in mind. Rely ONLY on the context from Wikipedia.

Context from Wikipedia:
{context}

{history_context}Question: {original_query}

Instructions:
1. Provide a detailed, accurate response relying ONLY on the context information above.
2. If the context does not contain enough information to answer the question, state that you cannot find the answer in the retrieved Wikipedia articles, but still summarize whatever relevant context was found.
3. Keep the response clear, structured, and easy to read.
"""
    try:
        client = genai.Client(api_key=api_key)
        # Use Gemini 2.5 Flash for fast response times
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text, citations
    except Exception as e:
        raise Exception(f"Failed with Gemini API: {str(e)}")

@app.post("/api/chat")
async def chat(request: ChatRequest):
    # Verify API key configuration dynamically
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        return {
            "answer": "⚠️ **Gemini API key is not configured.**\n\nPlease add your `GEMINI_API_KEY` to the `.env` file in the project directory, then restart the backend server.",
            "citations": []
        }

    user_query = request.message.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    search_query = user_query

    # Query reformulation if history is present
    if request.history:
        try:
            client = genai.Client(api_key=api_key)
            history_str = "\n".join([f"{msg.role}: {msg.content}" for msg in request.history])
            
            rewrite_prompt = f"""You are a query reformulation assistant. Given the following conversation history and a follow-up question, rewrite the follow-up question into a single, standalone search query to search Wikipedia.
            
Requirements:
1. The query must be concise and contain the specific names/subjects from the history (e.g. rewrite "when was he born" to "Nikola Tesla birth date").
2. Do not include search operators like AND, OR, site:, or quotes.
3. If the question is already standalone and does not refer to history, return it exactly as is.
4. Return ONLY the search query text, with no introduction or extra explanation.

Conversation History:
{history_str}

Follow-up Question: {user_query}
"""
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=rewrite_prompt
            )
            rewritten = response.text.strip().strip('"').strip("'")
            if rewritten:
                print(f"Reformulated query: '{user_query}' -> '{rewritten}'")
                search_query = rewritten
        except Exception as e:
            print(f"Failed to reformulate query: {e}")

    try:
        # 1. Search Wikipedia using reformulated query
        articles, error = get_wikipedia_content(search_query)
        if error:
            return {"answer": f"Error searching Wikipedia: {error}", "citations": []}
        if not articles:
            return {"answer": f"No relevant Wikipedia articles were found for \"{search_query}\".", "citations": []}

        # 2. Build local FAISS Vector store
        vector_store = create_vector_store(articles, api_key)
        
        # 3. Retrieve relevant chunks and generate answer
        answer, citations = get_answer(search_query, user_query, vector_store, articles, api_key, request.history)

        return {
            "answer": answer,
            "citations": citations
        }
    except Exception as e:
        return {
            "answer": f"An error occurred while processing your request: {str(e)}",
            "citations": []
        }

# Mount static files directory
# Create directory 'static' if it doesn't exist
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
