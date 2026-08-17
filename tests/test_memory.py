import pytest
import json
import os
from src.memory import load_memory, save_memory

def test_load_memory():
    memory = load_memory()
    assert "user_name" in memory
    assert "key_facts" in memory
    assert "chat_history" in memory