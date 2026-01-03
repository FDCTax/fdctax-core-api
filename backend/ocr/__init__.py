"""
OCR Module (A3-OCR-01)

Receipt image OCR processing using OpenAI Vision API.
- Downloads receipt images from URLs
- Extracts structured data (vendor, amount, date, items)
- Links results to ingestion transactions
- Stores attachments with OCR results
"""

from ocr.services.ocr_service import OCRService, OCRResult, ocr_service
from ocr.endpoints.ocr_api import router as ocr_router

__all__ = [
    'OCRService',
    'OCRResult',
    'ocr_service',
    'ocr_router'
]
