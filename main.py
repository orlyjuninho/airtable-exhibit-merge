from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict
import requests
import io
import os
import uuid
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.colors import blue
from reportlab.pdfbase.pdfmetrics import stringWidth
from collections import defaultdict

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    width, height = LETTER
    can.setFont("Helvetica-Bold", font_size)
    can.drawCentredString(width / 2.0, height / 2.0, text)
    can.save()
    packet.seek(0)
    return PdfReader(packet)

def add_page_numbers(reader: PdfReader, start_at=1):
    writer = PdfWriter()
    total_pages = len(reader.pages)
    for i in range(total_pages):
        page = reader.pages[i]
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=LETTER)
        width, height = LETTER
        can.setFont("Helvetica", 12)
        can.setFillColor(blue)
        can.drawRightString(width - 30, 15, str(start_at + i))
        can.save()
        packet.seek(0)
        overlay = PdfReader(packet)
        page.merge_page(overlay.pages[0])
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return PdfReader(output)

def download_pdf(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/pdf"
        }
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        if b"%PDF" not in r.content[:1024]:
            raise Exception("Arquivo baixado não parece ser um PDF.")
        return PdfReader(io.BytesIO(r.content))
    except Exception as e:
        raise Exception(f"Erro ao baixar ou carregar PDF da URL: {url}\n{str(e)}")

def generate_index(exhibits):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=LETTER)
    width, height = LETTER
    left_margin = 70
    right_margin = width - 50
    max_text_width = right_margin - left_margin - 80

    can.setFont("Helvetica-Bold", 18)
    can.drawCentredString(width / 2.0, height - 60, "Exhibit List")

    y = height - 90
    for item, page, bold in exhibits:
        if bold:
            can.setFont("Helvetica-Bold", 12)
        else:
            can.setFont("Helvetica", 12)

        words = item.split()
        current_line = ""
        lines = []
        for word in words:
            test_line = f"{current_line} {word}".strip()
            if stringWidth(test_line, can._fontname, 12) < max_text_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        lines.append(current_line)

        for i, line in enumerate(lines):
            can.drawString(left_margin, y, line)
            if i == len(lines) - 1:
                can.drawRightString(right_margin, y, page)
            y -= 20
            if y < 50:
                can.showPage()
                y = height - 60

        if bold:
            y -= 10

    can.save()
    packet.seek(0)
    return PdfReader(packet)

@app.post("/merge")
async def merge_docs(request: Request):
    try:
        data = await request.json()
        print("📥 Dados recebidos:", data)

        documentos = data["documentos"]
        merger = PdfMerger()
        page_counter = 1
        temp_outputs = []
        exhibit_list = []

        grouped: Dict[str, List[Documento]] = defaultdict(list)
        section_order = {}

        for doc in documentos:
            grouped[doc["secao"]].append(doc)
            if doc["secao"] not in section_order:
                section_order[doc["secao"]] = doc["ordem"]

        sorted_sections = sorted(grouped.items(), key=lambda x: section_order.get(x[0], 999))

        for secao, docs in sorted_sections:
            cover = create_text_page(secao)
            cover_numbered = add_page_numbers(cover, page_counter)
            temp_outputs.append((cover_numbered, 1))
            exhibit_list.append((secao, str(page_counter), True))
            page_counter += 1

            docs_sorted = sorted(docs, key=lambda d: d["titulo"])
            for doc in docs_sorted:
                print(f"🔗 Baixando PDF: {doc['pdf_url']}")
                pdf = download_pdf(doc["pdf_url"])
                num_pages = len(pdf.pages)
                page_range = f"{page_counter}-{page_counter + num_pages - 1}" if num_pages > 1 else str(page_counter)
                exhibit_list.append((doc["titulo"], page_range, False))
                numbered = add_page_numbers(pdf, page_counter)
                temp_outputs.append((numbered, num_pages))
                page_counter += num_pages

        index_pdf = generate_index(exhibit_list)
        temp_outputs.insert(0, (index_pdf, len(index_pdf.pages)))

        for pdf, _ in temp_outputs:
            merger.append(pdf)

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
