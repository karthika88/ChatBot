from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from app.database import candidates_collection
import PyPDF2
import docx
import io
import logging
from datetime import datetime
from bson import ObjectId

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
model = SentenceTransformer('all-MiniLM-L6-v2')
index = faiss.IndexFlatL2(384)

def extract_text_from_pdf(file_bytes):
    try:
        pdf_file = io.BytesIO(file_bytes)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = "".join([page.extract_text() for page in pdf_reader.pages])
        return text.strip()
    except Exception as e:
        logger.error(f"PDF extraction error: {str(e)}")
        raise HTTPException(status_code=400, detail="Could not process PDF file")

def extract_text_from_docx(file_bytes):
    try:
        doc_file = io.BytesIO(file_bytes)
        doc = docx.Document(doc_file)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        return text.strip()
    except Exception as e:
        logger.error(f"DOCX extraction error: {str(e)}")
        raise HTTPException(status_code=400, detail="Could not process DOCX file")

JOB_DESCRIPTIONS = {
    "software-engineer": """Muhammed Ajmal T
Email: muhammedajmalt23@gmail.com | Phone: 6282530313| LinkedIn:
linkedin.com/in/johndoe
Summary:
Highly skilled Software Engineer with 5+ years of experience in developing, testing, and
maintaining software applications. Proficient in Python, Java, and C++, with expertise in
backend development, cloud computing, and DevOps.
Technical Skills:
- Programming: Python, Java, C++
- Web Development: Django, Flask, Spring Boot
- Databases: MySQL, PostgreSQL, MongoDB- DevOps: Docker, Kubernetes, CI/CD, AWS,
Azure
Experience:
Software Engineer | TechCorp Inc. | 2020 - Present
- Designed and developed scalable backend systems using Python and Java.
- Implemented RESTful APIs and integrated with cloud-based services.
- Led a team of developers to optimize database queries and enhance application
performance.
Software Developer | CodeWorks | 2017 - 2020
- Developed real-time analytics applications using C++ and Python.
- Improved system performance by 30% through optimized algorithms.
- Collaborated with cross-functional teams to enhance software features.
Education:
Bachelor of Science in Computer Science | XYZ University | 2017
Certifications:
- AWS Certified Developer - Associate- Google Cloud Professional eveloper
Projects:
- Built a machine learning model for predictive analytics in e-commerce.
- Developed a microservices-based application for a fintech startup.""",
    "product-manager": """Product manager job responsibilities..."""
}

def calculate_similarity(embedding1, embedding2):
    faiss.normalize_L2(embedding1)
    faiss.normalize_L2(embedding2)
    return 1 - np.linalg.norm(embedding1 - embedding2)

@router.post("/upload_resume/")
async def upload_resume(
    file: UploadFile,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    position: str = Form(...)
):
    try:
        logger.info(f"Processing resume for {name} - Position: {position}")
        content = await file.read()
        
        # Extract text from resume
        file_extension = file.filename.lower().split('.')[-1]
        text = extract_text_from_pdf(content) if file_extension == 'pdf' else extract_text_from_docx(content)

        # Calculate match score
        resume_embedding = model.encode([text])
        job_embedding = model.encode([JOB_DESCRIPTIONS.get(position, "")])
        match_score = float(calculate_similarity(resume_embedding, job_embedding))

        # Create candidate record
        candidate_id = str(ObjectId())
        status = "Awaiting Scheduling" if match_score >= 0.7 else "Under Review"
        
        candidate_doc = {
            "_id": ObjectId(candidate_id),
            "name": name,
            "email": email,
            "phone": phone,
            "position": position,
            "resume_text": text,
            "match_score": match_score,
            "status": status,
            "application_date": datetime.utcnow()
        }
        
        await candidates_collection.insert_one(candidate_doc)

        return {
            "status": "success" if match_score >= 0.7 else "rejected",
            "candidate_id": candidate_id,
            "match_score": match_score,
            "message": "Application successful!" if match_score >= 0.7 else "Thank you for your application"
        }

    except Exception as e:
        logger.error(f"Error processing resume: {e}")
        raise HTTPException(status_code=500, detail=str(e))
