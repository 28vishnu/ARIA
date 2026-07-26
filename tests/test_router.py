import pytest
from main import GreetingHandler, IdentityHandler, ProfileHandler

def test_greeting_handler():
    handler = GreetingHandler()
    assert handler.can_handle("Hi") is True
    assert handler.can_handle("Good morning") is True
    assert handler.can_handle("Random query") is False

def test_identity_handler():
    handler = IdentityHandler()
    assert handler.can_handle("Who are you?") is True
    assert handler.can_handle("Your name?") is True
