# model.py
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel

class AttentionLayer(nn.Module):
    def __init__(self, hidden_size):
        super(AttentionLayer, self).__init__()
        self.attention = nn.Linear(hidden_size, 1)

    def forward(self, lstm_output):
        attention_weights = F.softmax(self.attention(lstm_output), dim=1)
        context_vector = torch.sum(attention_weights * lstm_output, dim=1)
        return context_vector

class TextClassificationModel(nn.Module):
    def __init__(self, n_classes, lstm_hidden_size=128, dropout_rate=0.3):
        super(TextClassificationModel, self).__init__()
        self.bert = AutoModel.from_pretrained("C:/Users/imanu/Documents/PROJECTS/Huggingface Model/indobert-base-uncased")
        self.lstm = nn.LSTM(self.bert.config.hidden_size, lstm_hidden_size, batch_first=True, bidirectional=True)
        self.attention = AttentionLayer(lstm_hidden_size * 2)
        
        self.fc1 = nn.Linear(lstm_hidden_size * 2 + self.bert.config.hidden_size, 256)
        self.fc2 = nn.Linear(256, 64)
        self.out = nn.Linear(64, n_classes)
        
        self.layer_norm1 = nn.LayerNorm(256)
        self.layer_norm2 = nn.LayerNorm(64)
        
        self.dropout = nn.Dropout(dropout_rate)
        self.relu = nn.ReLU()

    def forward(self, input_ids, attention_mask):
        # BERT layer
        bert_output, pooled_output = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            return_dict=False
        )
        
        # LSTM layer
        lstm_output, _ = self.lstm(bert_output)
        
        # Attention layer
        attn_output = self.attention(lstm_output)
        
        # Concatenate BERT pooled output and LSTM attention output
        combined = torch.cat((pooled_output, attn_output), dim=1)
        
        # Fully connected layers with residual connections and layer normalization
        fc1_output = self.fc1(combined)
        fc1_output = self.layer_norm1(fc1_output + self.dropout(self.relu(fc1_output)))
        
        fc2_output = self.fc2(fc1_output)
        fc2_output = self.layer_norm2(fc2_output + self.dropout(self.relu(fc2_output)))
        
        # Output layer
        output = self.out(fc2_output)
        return output