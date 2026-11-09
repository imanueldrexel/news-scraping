import torch
from .config import MODEL_PATH, DEVICE, N_CLASS, IDX2LABEL
from .model import TextClassificationModel
from .processor import preprocess

model = TextClassificationModel(n_classes=N_CLASS)  # Adjust num_classes as needed
model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
model.to(DEVICE)
model.eval()

def predict(text):
    inputs = preprocess(text)
    input_ids = inputs['input_ids'].to(DEVICE)
    attention_mask = inputs['attention_mask'].to(DEVICE)
    
    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
    
    probabilities = torch.softmax(outputs, dim=1)
    prediction = torch.argmax(probabilities, dim=1).item()
    confidence = probabilities[0][prediction].item()
    
    prediction = IDX2LABEL[prediction]
    return prediction, confidence