"""
conftest.py — Make the bot package importable from the tests/ directory.
"""
import sys
import os

# Add the pionex-grid-bot root to the path so tests can import bot modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
