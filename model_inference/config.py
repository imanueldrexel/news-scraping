import torch
import pickle

MODEL_PATH = 'best_model.pth'
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
MAX_LENGTH = 128  # or whatever max length you used during training
IDX2LABEL = pickle.load(open('idx2label.pkl','rb'))
N_CLASS = 13