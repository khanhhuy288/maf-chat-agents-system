"""Shared utility functions for the chat agents system."""

import json
import logging
from typing import Any


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse JSON from text, attempting to extract JSON fragment if full parse fails.
    
    This is useful for parsing LLM responses that may contain JSON embedded in other text.
    
    Args:
        text: The text to parse, which may contain JSON
        
    Returns:
        A dictionary with parsed JSON data, or empty dict if parsing fails
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Attempt to locate JSON substring
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            fragment = text[start : end + 1]
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                pass
    return {}


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given name.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        A configured logger instance
    """
    return logging.getLogger(name)

