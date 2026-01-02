"""
Normalisation Worker (A3-INGEST-03)

Background worker that processes the normalisation queue.
Can be run as a standalone process or triggered via API endpoint.

Usage:
- API trigger: POST /api/ingestion/normalisation/process
- Standalone: python -m ingestion.workers.normalisation_worker

Features:
- Batch processing
- Retry logic (3 attempts)
- Error isolation (failures don't crash queue)
- Audit logging
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class NormalisationWorker:
    """
    Background worker for normalisation queue processing.
    
    This worker:
    1. Polls the normalisation_queue table for pending items
    2. Processes each item by calling the NormalisationService
    3. Handles retries and error isolation
    4. Can run continuously or as a one-shot process
    """
    
    def __init__(
        self,
        db_session_factory,
        agent8_url: Optional[str] = None,
        batch_size: int = 10,
        poll_interval: int = 5
    ):
        """
        Initialize the worker.
        
        Args:
            db_session_factory: SQLAlchemy async session factory
            agent8_url: URL of Agent 8's mapping service (None = use mock)
            batch_size: Number of queue items to process per batch
            poll_interval: Seconds between polls when running continuously
        """
        self.db_session_factory = db_session_factory
        self.agent8_url = agent8_url
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self._running = False
    
    async def process_once(self) -> dict:
        """
        Process one batch of queue items.
        
        Returns:
            Processing statistics
        """
        from ingestion.services.normalisation_service import NormalisationService
        
        async with self.db_session_factory() as db:
            service = NormalisationService(db, agent8_url=self.agent8_url)
            
            results = await service.process_queue(batch_size=self.batch_size)
            
            total_processed = sum(r.transactions_processed for r in results)
            total_succeeded = sum(r.transactions_succeeded for r in results)
            total_failed = sum(r.transactions_failed for r in results)
            
            return {
                "queue_items_processed": len(results),
                "transactions_processed": total_processed,
                "transactions_succeeded": total_succeeded,
                "transactions_failed": total_failed,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    async def run_continuous(self):
        """
        Run the worker continuously, polling for new items.
        
        Use Ctrl+C to stop.
        """
        self._running = True
        logger.info(f"Starting normalisation worker (batch_size={self.batch_size}, poll_interval={self.poll_interval}s)")
        
        while self._running:
            try:
                stats = await self.process_once()
                
                if stats["queue_items_processed"] > 0:
                    logger.info(
                        f"Processed {stats['queue_items_processed']} queue items: "
                        f"{stats['transactions_succeeded']} succeeded, "
                        f"{stats['transactions_failed']} failed"
                    )
                
            except Exception as e:
                logger.error(f"Worker error: {e}")
            
            await asyncio.sleep(self.poll_interval)
    
    def stop(self):
        """Stop the continuous worker."""
        self._running = False
        logger.info("Normalisation worker stopping...")


async def run_worker():
    """Run the normalisation worker as a standalone process."""
    import os
    import sys
    
    # Add backend to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    from database.connection import engine, AsyncSessionLocal
    
    # Get Agent 8 URL from environment
    agent8_url = os.environ.get("AGENT8_MAPPING_URL")
    
    worker = NormalisationWorker(
        db_session_factory=AsyncSessionLocal,
        agent8_url=agent8_url,
        batch_size=10,
        poll_interval=5
    )
    
    try:
        await worker.run_continuous()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    asyncio.run(run_worker())
