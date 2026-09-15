#!/bin/bash
# Pull required Ollama models

echo "Pulling Ollama models..."

# Wait for Ollama to be ready
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    echo "Waiting for Ollama..."
    sleep 5
done

echo "Ollama is ready!"

# Pull embedding model
echo "Pulling nomic-embed-text..."
curl -X POST http://localhost:11434/api/pull -d '{"name": "nomic-embed-text"}'

# Pull LLM model
echo "Pulling qwen2.5:7b-instruct..."
curl -X POST http://localhost:11434/api/pull -d '{"name": "qwen2.5:7b-instruct"}'

echo "All models pulled successfully!"

# Verify models
echo "Available models:"
curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; models=json.load(sys.stdin).get('models',[]); print('\n'.join(m['name'] for m in models))"
