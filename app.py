import os
import glob
import threading
import webbrowser
import traceback
from dotenv import load_dotenv

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.vectorstores import FAISS

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
DOCS_DIR       = os.getenv("DOCS_DIR", "./docs")
INDEX_DIR      = os.getenv("INDEX_DIR", "./nextek_index")
LLM_MODEL      = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")

if not GOOGLE_API_KEY:
    raise ValueError("No se encontró GOOGLE_API_KEY en el archivo .env")

app = FastAPI(title="NexTek AI Agent", version="2.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("assets", exist_ok=True)
app.mount("/assets", StaticFiles(directory="assets"), name="assets")

embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=GOOGLE_API_KEY
)

llm = ChatGoogleGenerativeAI(
    model=LLM_MODEL,
    google_api_key=GOOGLE_API_KEY,
    temperature=0.1,
    max_output_tokens=350
)

output_parser = StrOutputParser()

def obtener_vectorstore():
    if os.path.exists(INDEX_DIR) and os.path.exists(os.path.join(INDEX_DIR, "index.faiss")):
        return FAISS.load_local(INDEX_DIR, embeddings, allow_dangerous_deserialization=True)
    return None

vectorstore = obtener_vectorstore()

class PreguntaRequest(BaseModel):
    pregunta: str

NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}

@app.get("/")
@app.get("/index.html")
def vista_inicio():
    return FileResponse("index.html", headers=NO_CACHE_HEADERS)

@app.get("/estado")
def estado():
    return {
        "status": "ready" if vectorstore else "no_index",
        "modelo": LLM_MODEL,
        "fragmentos": vectorstore.index.ntotal if vectorstore else 0
    }

@app.post("/preguntar")
def responder(peticion: PreguntaRequest):
    pregunta = peticion.pregunta.strip()
    if not pregunta:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía.")
    if not vectorstore:
        return {
            "respuesta": "⚠️ Base vectorial no disponible. Verifica que la carpeta 'nextek_index' exista.",
            "sources": []
        }

    try:
        resultados = vectorstore.similarity_search_with_score(pregunta, k=2)
        UMBRAL_RELEVANCIA = 0.70
        docs_validos = [doc for doc, score in resultados if score <= UMBRAL_RELEVANCIA]

        sources = []
        if docs_validos:
            contexto = "\n\n".join(doc.page_content for doc in docs_validos)
            prompt_contextual = ChatPromptTemplate.from_template(
                """Eres el asistente oficial de atención y políticas de NexTek México.
Responde de forma concisa, cordial y directa basándote ÚNICAMENTE en este contexto oficial:

{context}

Pregunta del cliente: {question}
Respuesta:"""
            )
            cadena = prompt_contextual | llm | output_parser
            respuesta = cadena.invoke({"context": contexto, "question": pregunta})

            for doc in docs_validos:
                fuente = doc.metadata.get("source", "Documento")
                pagina = doc.metadata.get("page", 0) + 1
                etiqueta = f"{fuente} - pag. {pagina}"
                if etiqueta not in sources:
                    sources.append(etiqueta)
        else:
            prompt_general = ChatPromptTemplate.from_template(
                """Eres el asistente virtual oficial de NexTek México (tienda de tecnología y electrónica).
El usuario te saluda o pregunta: "{question}".

Instrucciones:
- Si es un saludo, responde amablemente y menciona que puedes orientarle en compras, políticas de garantía, devoluciones y el programa NexTek+.
- Si pregunta algo ajeno a la tienda, indica con cortesía que tu función es resolver dudas sobre las políticas de NexTek.
- No inventes políticas ni menciones documentos si no los tienes en el contexto.

Respuesta:"""
            )
            cadena = prompt_general | llm | output_parser
            respuesta = cadena.invoke({"question": pregunta})

        return {
            "respuesta": respuesta,
            "sources": sources
        }

    except Exception as e:
        print("\n" + "=" * 60)
        print(">>> ERROR EN /preguntar <<<")
        traceback.print_exc()
        print("=" * 60 + "\n")
        return {
            "respuesta": f"⚠️ Error al procesar consulta: {str(e)}",
            "sources": []
        }

if __name__ == "__main__":
    threading.Thread(target=lambda: webbrowser.open("http://127.0.0.1:8000"), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)