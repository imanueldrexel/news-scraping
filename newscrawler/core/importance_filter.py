import logging
from typing import List
from sentence_transformers import SentenceTransformer, util

# Configure logging
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class SemanticImportanceFilter:
    def __init__(self, interests: List[str], threshold: float = 0.35, model_name: str = 'all-MiniLM-L6-v2'):
        """
        Initialize the Semantic Importance Filter.
        
        Args:
            interests: List of strings describing the user's interests (e.g. "Artificial Intelligence", "Stock Market").
            threshold: Cosine similarity threshold (0 to 1). Articles above this are "important".
            model_name: Sentence Transformer model name.
        """
        logger.info(f"Loading Semantic Filter Model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.interests = interests
        self.threshold = threshold
        
        # Pre-encode interests for speed
        self.interest_embeddings = self.model.encode(self.interests, convert_to_tensor=True)
        logger.info(f"Initialized Semantic Filter with interests: {self.interests}")

    def is_important(self, text: str) -> bool:
        """
        Check if the text is semantically similar to any of the interests.
        """
        if not text:
            return False
            
        # Truncate text to first 200 words for speed and relevance (intros usually contain the topic)
        text_snippet = " ".join(text.split()[:200])
        
        # Encode the article text
        article_embedding = self.model.encode(text_snippet, convert_to_tensor=True)
        
        # Calculate cosine similarities
        cosine_scores = util.cos_sim(article_embedding, self.interest_embeddings)
        
        # Find the max similarity score
        max_score = float(cosine_scores.max())
        
        is_relevant = max_score >= self.threshold
        
        if is_relevant:
            logger.debug(f"Article matched with score {max_score:.3f}")
        
        return is_relevant
