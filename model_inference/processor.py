from transformers import AutoTokenizer
from .config import MAX_LENGTH

tokenizer = AutoTokenizer.from_pretrained("C:/Users/imanu/Documents/PROJECTS/Huggingface Model/indobert-base-uncased")

def preprocess(text):
    return tokenizer(text, padding='max_length', truncation=True, max_length=MAX_LENGTH, return_tensors='pt')
