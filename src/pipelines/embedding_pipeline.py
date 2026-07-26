"""
Embedding Pipeline: Converts job descriptions into vector embeddings and indexes them with FAISS.

Uses sentence-transformers/all-MiniLM-L6-v2 to generate 384-dimensional embeddings.
Indexes with FAISS using IndexFlatIP (inner product) with L2-normalized vectors to compute cosine similarity.
"""

import argparse
import json
import logging
import os
from typing import Any, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from src.config.settings import get_settings
from src.models.job import Job

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """Pipeline for embedding job descriptions and building FAISS index."""

    def __init__(self, index_dir: str = "data/faiss_index/", model: Any | None = None):
        """Initialize the embedding pipeline.

        Args:
            index_dir: Directory to store FAISS index and metadata files.
            model: Optional embedding model, mainly used for tests.
        """
        settings = get_settings()

        if model is None:
            logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
            model = SentenceTransformer(settings.EMBEDDING_MODEL)

        self.model = model
        self.model_dim = self.model.get_embedding_dimension()

        # Set up index directory and paths
        self.index_dir = index_dir
        os.makedirs(self.index_dir, exist_ok=True)

        self.index_path = os.path.join(self.index_dir, "jobs.index")
        self.metadata_path = os.path.join(self.index_dir, "jobs_metadata.json")

        # Try to load existing index, otherwise leave as None
        self.index: Optional[faiss.Index] = None
        self.metadata: dict = {}

        if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
            logger.info(f"Loading existing FAISS index from {self.index_path}")
            self.index = faiss.read_index(self.index_path)
            with open(self.metadata_path, "r") as f:
                metadata_list = json.load(f)
            self.metadata = {str(i): m for i, m in enumerate(metadata_list)}

    def embed_text(self, text: Optional[str]) -> np.ndarray:
        """Embed text into a vector.

        Returns zero-vector for None, empty, or very short text to avoid model overhead.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as float32 numpy array.
        """
        if text is None or len(str(text).strip()) < 3:
            return np.zeros(self.model_dim, dtype=np.float32)

        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)

    def build_index(self) -> None:
        """Build FAISS index from all non-spam jobs in the database."""
        from src.config.database import SessionLocal

        db = SessionLocal()
        try:
            # Query all non-spam jobs
            jobs = db.query(Job).filter(~Job.is_spam).all()

            if not jobs:
                logger.warning(
                    "No non-spam jobs found in database. Skipping index build."
                )
                return

            logger.info(f"Embedding {len(jobs)} jobs...")

            # Embed all jobs
            embeddings = []
            metadata_list = []

            for job in jobs:
                # Combine job fields
                combined_text = f"{job.role_title} {job.company_name} {job.jd_text}"
                embedding = self.embed_text(combined_text)

                # L2-normalize the embedding for cosine similarity via inner product
                embedding = embedding / (np.linalg.norm(embedding) + 1e-8)

                embeddings.append(embedding)
                metadata_list.append(
                    {
                        "job_id": job.id,
                        "role_title": job.role_title,
                        "company_name": job.company_name,
                    }
                )

            # Convert embeddings to numpy array
            embeddings_array = np.array(embeddings, dtype=np.float32)

            # Create FAISS index with inner product
            # IndexFlatIP with L2-normalized vectors = cosine similarity
            self.index = faiss.IndexFlatIP(self.model_dim)
            self.index.add(embeddings_array)

            # Save index and metadata
            faiss.write_index(self.index, self.index_path)
            logger.info(f"Saved FAISS index to {self.index_path}")

            with open(self.metadata_path, "w") as f:
                json.dump(metadata_list, f, indent=2)
            logger.info(f"Saved metadata to {self.metadata_path}")

            self.metadata = {str(i): m for i, m in enumerate(metadata_list)}
            logger.info(f"Successfully embedded {len(jobs)} jobs.")

        finally:
            db.close()

    def search(self, query_text: str, top_k: int = 5) -> list[dict]:
        """Search for the most similar jobs to a query.

        Args:
            query_text: Query text to search for.
            top_k: Number of top results to return.

        Returns:
            List of dicts with job_id, role_title, company_name, and score.

        Raises:
            RuntimeError: If no index has been built or loaded.
        """
        if self.index is None:
            raise RuntimeError(
                "No FAISS index available. Run build_index() first to build the index from jobs in the database."
            )

        # Embed and normalize query
        query_embedding = self.embed_text(query_text)
        query_embedding = query_embedding / (np.linalg.norm(query_embedding) + 1e-8)
        query_embedding = np.array([query_embedding], dtype=np.float32)

        # Search the index
        k_search = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_embedding, k_search)

        # Build results from metadata
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(self.metadata):
                meta_key = str(int(idx))
                if meta_key in self.metadata:
                    result = self.metadata[meta_key].copy()
                    result["score"] = float(score)
                    results.append(result)

        return results


def main():
    """CLI entry point for embedding pipeline."""
    parser = argparse.ArgumentParser(
        description="Embedding pipeline for HireFlow jobs."
    )
    parser.add_argument(
        "--embed-jobs",
        action="store_true",
        help="Build FAISS index from non-spam jobs in the database.",
    )

    args = parser.parse_args()

    if args.embed_jobs:
        logging.basicConfig(level=logging.INFO)
        pipeline = EmbeddingPipeline()
        pipeline.build_index()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
