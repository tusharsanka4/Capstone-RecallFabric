"""Download or verify the configured local embedding model."""

import argparse

from recallfabric.core.config import Settings
from recallfabric.embeddings.service import LocalEmbeddingProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Allow downloading model files")
    args = parser.parse_args()
    provider = LocalEmbeddingProvider(Settings())
    if args.download:
        provider.download()
    passage = provider.embed("A user is learning Python programming.")
    query = provider.embed("Which programming language is the user learning?", kind="query")
    print(f"Model: {passage.model}; dimensions: {passage.dimensions}")
    print(f"Passage and query inference passed ({len(query.vector)} query dimensions).")


if __name__ == "__main__":
    main()
