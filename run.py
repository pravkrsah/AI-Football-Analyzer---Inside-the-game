"""Entry point: python run.py"""
import backend.config as config
import backend.embedding_search as embedding
from backend.database import init_db
from backend.main import create_server

if __name__ == "__main__":
    config.validate()
    init_db()
    try:
        embedding.load_historical_moments()
    except Exception as e:
        print(f"[WARNING] Embedding preload failed: {e}")
        print("[WARNING] Semantic search will be unavailable until the embedding endpoint is reachable.")

    server = create_server(port=8000)
    print("Football AI — Inside the Game")
    print("Server running at http://localhost:8000")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
