"""
OCR Service (A3-OCR-01)

Handles receipt image OCR processing using OpenAI Vision API.
Integrates with Secret Authority for secure key management.

Flow:
1. Accept file URL from client
2. Download file to local storage
3. Send to OpenAI Vision API for OCR
4. Return structured receipt data
"""

import os
import uuid
import base64
import logging
import httpx
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

from ingestion.unified_schema import AttachmentRef, OCRStatus

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Structured OCR extraction result."""
    success: bool
    vendor: Optional[str] = None
    amount: Optional[Decimal] = None
    date: Optional[str] = None
    description: Optional[str] = None
    gst_amount: Optional[Decimal] = None
    gst_included: bool = True
    items: Optional[list] = None
    raw_text: Optional[str] = None
    confidence: float = 0.0
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "vendor": self.vendor,
            "amount": str(self.amount) if self.amount else None,
            "date": self.date,
            "description": self.description,
            "gst_amount": str(self.gst_amount) if self.gst_amount else None,
            "gst_included": self.gst_included,
            "items": self.items,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "error_message": self.error_message
        }


class OCRService:
    """
    Service for processing receipt images with OCR.
    
    Uses OpenAI Vision API via emergentintegrations library
    with Emergent LLM Key for authentication.
    """
    
    # Supported image formats
    SUPPORTED_FORMATS = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp',
        'application/pdf': '.pdf'
    }
    
    # Max file size (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    # System prompt for receipt OCR
    RECEIPT_OCR_PROMPT = """You are a receipt OCR specialist. Analyze the receipt image and extract the following information in JSON format:

{
    "vendor": "Store/business name",
    "date": "YYYY-MM-DD format if visible",
    "amount": "Total amount as a number (e.g., 45.50)",
    "gst_amount": "GST/tax amount as a number if shown separately",
    "gst_included": true/false (whether GST is included in total),
    "description": "Brief description of purchase",
    "items": [
        {"name": "Item name", "quantity": 1, "price": 10.00}
    ],
    "raw_text": "Full extracted text from receipt",
    "confidence": 0.0-1.0 (how confident you are in the extraction)
}

Important:
- Extract ALL visible text
- If a field is not visible, use null
- Amounts should be numbers only (no currency symbols)
- Dates should be in YYYY-MM-DD format
- For Australian receipts, GST is typically 10% and included in the total"""

    def __init__(self):
        self.storage_base = os.environ.get('STORAGE_REF_BASE', '/app/storage/receipts')
        self.api_key = os.environ.get('EMERGENT_LLM_KEY', '')
        
        # Ensure storage directory exists
        Path(self.storage_base).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"OCRService initialized with storage: {self.storage_base}")
    
    async def process_receipt(
        self,
        file_url: str,
        client_id: str,
        transaction_id: Optional[str] = None
    ) -> Tuple[OCRResult, Optional[AttachmentRef]]:
        """
        Process a receipt image from URL.
        
        Args:
            file_url: URL of the receipt image
            client_id: Core client ID
            transaction_id: Optional transaction to link to
            
        Returns:
            Tuple of (OCRResult, AttachmentRef or None)
        """
        attachment = None
        
        try:
            # Step 1: Download file
            logger.info(f"Downloading receipt from: {file_url[:50]}...")
            file_path, file_info = await self._download_file(file_url, client_id)
            
            # Step 2: Create attachment reference
            attachment = AttachmentRef(
                file_name=file_info['file_name'],
                file_type=file_info['mime_type'],
                file_size=file_info['file_size'],
                storage_path=file_path,
                ocr_status=OCRStatus.PENDING
            )
            
            # Step 3: Perform OCR
            logger.info(f"Performing OCR on: {file_path}")
            ocr_result = await self._perform_ocr(file_path, file_info['mime_type'])
            
            # Step 4: Update attachment with OCR result
            if ocr_result.success:
                attachment.ocr_status = OCRStatus.PROCESSED
                attachment.ocr_result = ocr_result.to_dict()
            else:
                attachment.ocr_status = OCRStatus.FAILED
                attachment.ocr_result = {"error": ocr_result.error_message}
            
            return ocr_result, attachment
            
        except ValueError as e:
            # Validation errors
            logger.warning(f"OCR validation error: {e}")
            return OCRResult(
                success=False,
                error_message=str(e)
            ), attachment
            
        except Exception as e:
            # Unexpected errors
            logger.error(f"OCR processing error: {e}")
            if attachment:
                attachment.ocr_status = OCRStatus.FAILED
                attachment.ocr_result = {"error": str(e)}
            
            return OCRResult(
                success=False,
                error_message=f"OCR processing failed: {str(e)}"
            ), attachment
    
    async def _download_file(
        self,
        file_url: str,
        client_id: str
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Download file from URL to local storage.
        
        Args:
            file_url: URL to download from
            client_id: Client ID for organizing storage
            
        Returns:
            Tuple of (local_path, file_info)
        """
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(file_url)
                response.raise_for_status()
                
                # Get content type
                content_type = response.headers.get('content-type', '').split(';')[0].strip()
                
                # Validate content type
                if content_type not in self.SUPPORTED_FORMATS:
                    raise ValueError(
                        f"Unsupported file format: {content_type}. "
                        f"Supported: {list(self.SUPPORTED_FORMATS.keys())}"
                    )
                
                # Get file content
                content = response.content
                file_size = len(content)
                
                # Validate file size
                if file_size > self.MAX_FILE_SIZE:
                    raise ValueError(
                        f"File too large: {file_size} bytes. Max: {self.MAX_FILE_SIZE} bytes"
                    )
                
                if file_size == 0:
                    raise ValueError("Downloaded file is empty")
                
                # Generate unique filename
                file_ext = self.SUPPORTED_FORMATS[content_type]
                file_id = str(uuid.uuid4())
                file_name = f"{file_id}{file_ext}"
                
                # Create client directory
                client_dir = Path(self.storage_base) / client_id
                client_dir.mkdir(parents=True, exist_ok=True)
                
                # Save file
                local_path = client_dir / file_name
                local_path.write_bytes(content)
                
                logger.info(f"Downloaded file to: {local_path} ({file_size} bytes)")
                
                return str(local_path), {
                    "file_name": file_name,
                    "mime_type": content_type,
                    "file_size": file_size,
                    "original_url": file_url
                }
                
        except httpx.HTTPStatusError as e:
            raise ValueError(f"Failed to download file: HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            raise ValueError(f"Failed to download file: {str(e)}")
    
    async def _perform_ocr(
        self,
        file_path: str,
        mime_type: str
    ) -> OCRResult:
        """
        Perform OCR on a local image file using OpenAI Vision API.
        
        Args:
            file_path: Path to local image file
            mime_type: MIME type of the file
            
        Returns:
            OCRResult with extracted data
        """
        if not self.api_key:
            raise ValueError("EMERGENT_LLM_KEY not configured")
        
        try:
            # Read and encode image as base64
            with open(file_path, 'rb') as f:
                image_bytes = f.read()
            
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # Create chat instance with OpenAI GPT-4 Vision using Emergent LLM key
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"ocr-{uuid.uuid4()}",
                system_message=self.RECEIPT_OCR_PROMPT
            ).with_model("openai", "gpt-4o")  # Use GPT-4o for vision capabilities
            
            # Create image content - emergentintegrations uses ImageContent for base64 images
            image_content = ImageContent(image_base64=image_base64)
            
            # Create message with image
            # The library expects text in one message and image in another via file_contents
            user_message = UserMessage(
                text="Please analyze this receipt image and extract all information in the specified JSON format.",
                file_contents=[image_content]
            )
            
            # Send to OpenAI Vision API via Emergent proxy
            logger.info("Sending image to OpenAI Vision API via Emergent...")
            response = await chat.send_message(user_message)
            
            # Parse response
            return self._parse_ocr_response(response)
            
        except Exception as e:
            logger.error(f"OCR API error: {e}")
            return OCRResult(
                success=False,
                error_message=f"OCR API error: {str(e)}"
            )
    
    def _parse_ocr_response(self, response: str) -> OCRResult:
        """
        Parse the OCR response from OpenAI Vision API.
        
        Args:
            response: Raw response string from API
            
        Returns:
            Structured OCRResult
        """
        import json
        import re
        
        try:
            # Try to extract JSON from response
            # Look for JSON block in markdown or raw JSON
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    # No JSON found, treat entire response as raw text
                    return OCRResult(
                        success=True,
                        raw_text=response,
                        confidence=0.5,
                        description="Raw text extraction (no structured data found)"
                    )
            
            # Parse JSON
            data = json.loads(json_str)
            
            # Extract fields with validation
            amount = None
            if data.get('amount') is not None:
                try:
                    amount = Decimal(str(data['amount']))
                except:
                    pass
            
            gst_amount = None
            if data.get('gst_amount') is not None:
                try:
                    gst_amount = Decimal(str(data['gst_amount']))
                except:
                    pass
            
            confidence = data.get('confidence', 0.8)
            if not isinstance(confidence, (int, float)):
                confidence = 0.8
            
            return OCRResult(
                success=True,
                vendor=data.get('vendor'),
                amount=amount,
                date=data.get('date'),
                description=data.get('description'),
                gst_amount=gst_amount,
                gst_included=data.get('gst_included', True),
                items=data.get('items'),
                raw_text=data.get('raw_text'),
                confidence=float(confidence)
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse OCR JSON: {e}")
            return OCRResult(
                success=True,
                raw_text=response,
                confidence=0.5,
                description="Raw text extraction (JSON parse failed)"
            )
        except Exception as e:
            logger.error(f"Failed to parse OCR response: {e}")
            return OCRResult(
                success=False,
                error_message=f"Failed to parse OCR response: {str(e)}"
            )
    
    def validate_file_url(self, file_url: str) -> bool:
        """Validate that file URL is acceptable."""
        if not file_url:
            return False
        
        # Must be HTTP(S)
        if not file_url.startswith(('http://', 'https://')):
            return False
        
        return True


# Global service instance
ocr_service = OCRService()
