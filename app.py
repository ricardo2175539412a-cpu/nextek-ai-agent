"""
NexTek AI Agent - API principal
Construido con FastAPI + LangChain + Google Gemini

Este archivo levanta el servidor y expone los endpoints
para que cualquier cliente (chat.html, Postman, etc.)
pueda hacerle preguntas al agente en lenguaje natural.
"""

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from dotenv import load_dotenv

# Cargamos las variables de entorno desde el archivo .env
load_dotenv()

# --- Configuracion general ---
# Estas variables se leen del .env para no hardcodear datos sensibles
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
DOCS_DIR       = os.getenv("DOCS_DIR", "./Docs")
INDEX_DIR      = os.getenv("INDEX_DIR", "./nextek_index")

# Variables globales donde vivira el agente una vez inicializado
agente      = None
retriever   = None
vectorstore = None


# --- Prompt del agente ---
# Le decimos a Gemini exactamente como debe comportarse
# Mantenerlo claro y con reglas especificas mejora mucho la calidad de las respuestas
PROMPT_TEMPLATE = """Eres el asistente virtual oficial de NexTek, una tienda de
comercio electronico especializada en electronica y tecnologia en Mexico.

Tu funcion es responder preguntas sobre los documentos internos de NexTek:
politica de privacidad, politica de reembolsos y devoluciones, preguntas
frecuentes, guia de envios y terminos y condiciones.

REGLAS:
- Responde SIEMPRE en español, de forma clara y amigable.
- Basa tu respuesta UNICAMENTE en el contexto proporcionado.
- Si la informacion no esta en los documentos responde exactamente:
  Esa informacion no se encuentra en los documentos de NexTek.
- Usa listas cuando la respuesta tenga varios puntos.
- No inventes informacion.

CONTEXTO:
{context}

PREGUNTA:
{question}

RESPUESTA:"""


def format_docs(docs):
    """Une todos los fragmentos recuperados en un solo bloque de texto."""
    return "\n\n".join(doc.page_content for doc in docs)


def build_index():
    """
    Lee todos los PDFs de la carpeta docs/, los divide en fragmentos
    y construye el indice vectorial FAISS con embeddings de Gemini.

    Solo se ejecuta la primera vez o cuando los documentos cambian.
    El indice se guarda en disco para no tener que reconstruirlo cada vez.
    """
    print("[INFO] Leyendo documentos PDF...")
    all_documents = []

    pdf_files = sorted([f for f in os.listdir(DOCS_DIR) if f.endswith(".pdf")])
    if not pdf_files:
        raise FileNotFoundError(f"No encontre PDFs en la carpeta: {DOCS_DIR}")

    for pdf_file in pdf_files:
        path = os.path.join(DOCS_DIR, pdf_file)
        loader = PyPDFLoader(path)
        pages = loader.load()
        all_documents.extend(pages)
        print(f"[INFO] Cargado: {pdf_file} ({len(pages)} paginas)")

    print(f"[INFO] Total de paginas procesadas: {len(all_documents)}")

    # Dividimos el texto en chunks de 1500 caracteres con algo de solapamiento
    # para no perder contexto en los bordes de cada fragmento
    print("[INFO] Dividiendo texto en fragmentos...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = splitter.split_documents(all_documents)
    print(f"[INFO] Fragmentos generados: {len(chunks)}")

    # Generamos los embeddings con Gemini
    # Usamos lotes de 50 para respetar el limite del plan gratuito de la API
    print("[INFO] Generando embeddings con Gemini...")
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GOOGLE_API_KEY
    )

    batch_size = 50
    batches = [chunks[i:i+batch_size] for i in range(0, len(chunks), batch_size)]
    vs = None

    for idx, batch in enumerate(batches):
        print(f"[INFO] Procesando lote {idx+1} de {len(batches)}...")
        if vs is None:
            vs = FAISS.from_documents(batch, embeddings)
        else:
            vs.add_documents(batch)
        # Pausa entre lotes para no exceder el rate limit gratuito
        if idx < len(batches) - 1:
            time.sleep(15)

    vs.save_local(INDEX_DIR)
    print(f"[INFO] Indice guardado en: {INDEX_DIR}")
    return vs, embeddings


def load_index():
    """
    Carga el indice FAISS desde disco.
    Mucho mas rapido que reconstruirlo desde cero.
    """
    print("[INFO] Cargando indice FAISS desde disco...")
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GOOGLE_API_KEY
    )
    vs = FAISS.load_local(
        INDEX_DIR,
        embeddings,
        allow_dangerous_deserialization=True
    )
    print(f"[INFO] Indice listo con {vs.index.ntotal} fragmentos")
    return vs, embeddings


def build_agent(vs):
    """
    Arma la cadena RAG (Retrieval-Augmented Generation):
    1. El retriever busca los 5 fragmentos mas relevantes para la pregunta
    2. El prompt los combina con la pregunta
    3. Gemini genera la respuesta final
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=GOOGLE_API_KEY,
        temperature=0.2  # Valor bajo = respuestas mas precisas y consistentes
    )

    ret = vs.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 5}
    )

    prompt = PromptTemplate(
        template=PROMPT_TEMPLATE,
        input_variables=["context", "question"]
    )

    # Cadena LCEL (LangChain Expression Language)
    chain = (
        {
            "context":  ret | format_docs,
            "question": RunnablePassthrough()
        }
        | prompt
        | llm
        | StrOutputParser()
    )

    return chain, ret


# --- Ciclo de vida de la aplicacion ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Se ejecuta al arrancar y al apagar el servidor.
    Al arrancar: carga o construye el indice y prepara el agente.
    Al apagar: limpieza general.
    """
    global agente, retriever, vectorstore

    if not GOOGLE_API_KEY:
        raise ValueError("Falta configurar GOOGLE_API_KEY en el archivo .env")

    # Si el indice ya existe en disco lo cargamos directamente
    # Si no existe, lo construimos desde los PDFs (tarda mas la primera vez)
    if os.path.exists(INDEX_DIR):
        vectorstore, _ = load_index()
    else:
        os.makedirs(DOCS_DIR, exist_ok=True)
        vectorstore, _ = build_index()

    agente, retriever = build_agent(vectorstore)
    print("[INFO] Agente NexTek listo para recibir preguntas.")
    yield
    print("[INFO] Servidor apagado.")


# --- Inicializacion de FastAPI ---
app = FastAPI(
    title="NexTek AI Agent",
    description="Agente de IA para consulta de documentos internos de NexTek",
    version="1.0.0",
    lifespan=lifespan
)

# Permitimos peticiones desde cualquier origen (necesario para que chat.html funcione)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servimos el chat.html directamente desde el servidor
app.mount("/static", StaticFiles(directory="."), name="static")


# --- Modelos de datos ---
class PreguntaRequest(BaseModel):
    pregunta: str

class RespuestaResponse(BaseModel):
    pregunta:  str
    respuesta: str
    fuentes:   list[str]


# --- Endpoints ---
@app.get("/")
def root():
    """Pagina de bienvenida con informacion basica de la API."""
    return {
        "mensaje": "NexTek AI Agent activo",
        "version": "1.0.0",
        "chat":    "/chat",
        "docs":    "/docs",
        "uso":     "POST /preguntar con JSON: {pregunta: tu pregunta}"
    }


@app.get("/chat")
def chat_ui():
    """Sirve la interfaz de chat visual."""
    return FileResponse("chat.html")


@app.get("/health")
def health():
    """Verifica que el agente este inicializado y listo."""
    return {
        "status":     "ok",
        "agente":     agente is not None,
        "fragmentos": vectorstore.index.ntotal if vectorstore else 0
    }


@app.post("/preguntar", response_model=RespuestaResponse)
def preguntar(request: PreguntaRequest):
    """
    Endpoint principal del agente.
    Recibe una pregunta y devuelve la respuesta con sus fuentes.
    """
    if not agente:
        raise HTTPException(status_code=503, detail="El agente no esta listo todavia.")

    pregunta = request.pregunta.strip()
    if not pregunta:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacia.")

    try:
        # Obtenemos la respuesta del agente
        respuesta = agente.invoke(pregunta)

        # Recuperamos los documentos fuente para mostrarlos al usuario
        docs = retriever.invoke(pregunta)
        fuentes_vistas = set()
        fuentes = []
        for doc in docs:
            fuente = doc.metadata.get("source", "Desconocida").split("/")[-1]
            pagina = doc.metadata.get("page", "?")
            clave  = f"{fuente} - pag. {pagina}"
            if clave not in fuentes_vistas:
                fuentes.append(clave)
                fuentes_vistas.add(clave)

        return RespuestaResponse(
            pregunta=pregunta,
            respuesta=respuesta,
            fuentes=fuentes
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ejemplos")
def ejemplos():
    """Lista de preguntas de ejemplo para probar el agente."""
    return {
        "preguntas_ejemplo": [
            "Cuanto tiempo tengo para devolver un smartphone?",
            "El envio es gratis en NexTek?",
            "Como puedo ejercer mis derechos ARCO?",
            "Que metodos de pago aceptan?",
            "Que cubre la garantia NexTek?",
            "Como funciona el programa NexTek+?",
            "Que pasa si mi pedido llega danado?",
            "Puedo pagar con OXXO?"
        ]
    }
