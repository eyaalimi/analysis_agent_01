"""
conftest.py — pytest configuration at project root.
Adds the project root to sys.path so that all modules
(agents/, email_gateway/, config.py, etc.) are importable in tests.
"""
import sys
from pathlib import Path

# Insert project root at the front of sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
