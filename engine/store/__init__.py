"""Engine-local storage: embedding vectors, outbox log.

Empty in B0. Nothing about who worked when is ever written here — those records
belong to the backend (ARCHITECTURE.md §2.2). The engine keeps only what it
needs to recognise a face again: vectors, reference images, and the outbox of
events it has not yet handed over.
"""
