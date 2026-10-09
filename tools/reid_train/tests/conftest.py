"""Menaruh tools/reid_train di sys.path agar modul kit bisa diimpor langsung."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
