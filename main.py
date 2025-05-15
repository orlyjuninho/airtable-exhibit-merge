from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List
import requests
import io
import os
import uuid
from PyPDF2 import PdfMerger, PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER

app = FastAPI()

class Documento(BaseModel):
    ordem: int
    secao: str
    titulo: str
    pdf_url: str

class Payload(BaseModel):
    documentos: List[Documento]

def create_text_page(text, font_size=18):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=LETTER)
    can.setFont("Helvetica-Bold", font_size)
    width, height = LETTER
    can.drawCentredString(width / 2.0, height / 2.0, text)
    can.save()
    packet.seek(0)
    return PdfReader(packet)

def download_pdf(url):
    try:
        r = requests.get(url)
        r.raise_for_status()
        return PdfReader(io.BytesIO(r.content))
    except Exception as e:
        raise Exception(f"Erro ao baixar ou carregar PDF da URL: {url}\n{str(e)}")

def generate_index(exhibits):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=LETTER)
    can.setFont("Helvetica-Bold", 16)
    can.drawString(100, 750, "Exhibit List")
    can.setFont("Helvetica", 12)
    y = 720
    for item, page in exhibits:
        if page:
            can.drawString(100, y, f"{item} .......... {page}")
        else:
            can.setFont("Helvetica-Bold", 13)
            can.drawString(100, y, f"{item}")
            can.setFont("Helvetica", 12)
        y -= 20
        if y < 50:
            can.showPage()
            y = 750
    can.save()
    packet.seek(0)
    return PdfReader(packet)

@app.post("/merge")
async def merge_docs(request: Request):
    try:
        data = await request.json()
        print("📥 Dados recebidos:", data)

        documentos = sorted(data["documentos"], key=lambda x: x["ordem"])
        merger = PdfMerger()
        exhibit_list = []
        current_section = None
        page_counter = 1

        for doc in documentos:
            print(f"🔗 Baixando PDF: {doc['pdf_url']}")
            pdf = download_pdf(doc["pdf_url"])
            num_pages = len(pdf.pages)

            if doc["ordem"] == 0:
                merger.append(pdf)
                continue

            if doc["secao"] != current_section:
                current_section = doc["secao"]
                cover = create_text_page(current_section)
                merger.append(cover)
                page_counter += 1
                exhibit_list.append((current_section, None))

            start = page_counter
            end = start + num_pages - 1
            page_info = f"{start}-{end}" if start != end else str(start)
            exhibit_list.append((doc["titulo"], page_info))

            merger.append(pdf)
            page_counter += num_pages

        # Gera índice
        merger.merge(0, generate_index(exhibit_list))

        os.makedirs("static", exist_ok=True)
        filename = f"static/{uuid.uuid4().hex}.pdf"
        with open(filename, "wb") as f:
            merger.write(f)

        host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")
        url = f"https://{host}/{filename}"
        print("✅ PDF gerado:", url)
        return JSONResponse({"download_url": url})

    except Exception as e:
        print("❌ Erro no processamento:", str(e))
        return JSONResponse(status_code=500, content={"error": str(e)})
