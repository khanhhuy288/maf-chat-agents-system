import logging
import re
from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.schemas import TicketContext, TicketResponse
from obungi_chat_agents_system.utils import get_logger, parse_json_response

IDENTITY_PROMPT = """Du bist ein Assistent, der Kontaktdaten aus Text extrahiert.
Analysiere die Anfrage und gib ein JSON mit genau diesen Feldern zurück:
{
  "name": "<Nachname>",
  "vorname": "<Vorname>",
  "email": "<E-Mail-Adresse>"
}
Lass Felder leer, wenn sie nicht eindeutig genannt werden. Verwende keine Erklärungen.

Der Text kann in verschiedenen Formaten vorliegen:
1. Komma-getrennt: "Name, Vorname, E-Mail-Adresse" (z.B. "Müller, Hans, hans@example.com")
2. Natürliche Sprache: "mein Name ist [Vorname] [Nachname], meine E-Mail ist [email]" (z.B. "mein Name ist Peter Schneider, meine E-Mail ist peter@example.com")
3. Andere natürliche Formulierungen mit "Name ist", "E-Mail ist", "ich heiße", etc.

Extrahiere die Kontaktdaten aus dem Text, unabhängig vom Format.
Bei natürlicher Sprache: Der erste Name ist normalerweise der Vorname, der letzte Name ist der Nachname.
Bei komma-getrennten Formaten: Das erste Element ist der Nachname, das zweite der Vorname, und das dritte die E-Mail-Adresse.
"""


class IdentityExtractorExecutor(Executor):
    """LLM-backed extractor that pulls name/vorname/email from the original text."""

    _EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
    _NAME_HINTS = {
        "name": re.compile(r"\b(?:name|familienname)\b[:\-]?\s*(?P<value>[A-Za-zÄÖÜäöüß\s'-]+)", re.IGNORECASE),
        "vorname": re.compile(r"\bvorname\b[:\-]?\s*(?P<value>[A-Za-zÄÖÜäöüß\s'-]+)", re.IGNORECASE),
    }
    # Natural language patterns for German
    _NATURAL_NAME_PATTERNS = [
        # "mein Name ist Peter Schneider" or "Name ist Peter Schneider"
        # Handles punctuation and surrounding text
        re.compile(
            r"(?:mein\s+)?name\s+ist\s+(?P<vorname>[A-Za-zÄÖÜäöüß]+)\s+(?P<name>[A-Za-zÄÖÜäöüß]+)(?:[,\s]|$)",
            re.IGNORECASE
        ),
        # "ich heiße Peter Schneider" or "ich bin Peter Schneider"
        re.compile(
            r"ich\s+(?:heiße|bin)\s+(?P<vorname>[A-Za-zÄÖÜäöüß]+)\s+(?P<name>[A-Za-zÄÖÜäöüß]+)(?:[,\s]|$)",
            re.IGNORECASE
        ),
    ]
    _NATURAL_EMAIL_PATTERNS = [
        # "meine E-Mail ist peter@example.com" or "E-Mail ist peter@example.com"
        # Handles punctuation and surrounding text
        re.compile(
            r"(?:meine\s+)?(?:e-?mail|email)\s+ist\s+(?P<email>[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?:[,\s\.]|$)",
            re.IGNORECASE
        ),
    ]

    def __init__(self, chat_client: AzureOpenAIChatClient, id: str = "identity") -> None:
        self.agent = chat_client.create_agent(instructions=IDENTITY_PROMPT, name=id)
        super().__init__(id=id)

    @handler
    async def handle(
        self, context: TicketContext, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        """Extract identity information (name, vorname, email) from the original message.
        
        This executor handles both initial messages and follow-up messages where the user
        provides identity information after being asked for it. It uses regex fallback first
        (for reliability) and then LLM extraction if needed.
        
        When the message contains a separator (---), it extracts identity ONLY from the part
        after the separator, while preserving the full message for classification.
        """
        # Debug logging
        logger = get_logger(__name__)
        logger.debug(f"IdentityExtractorExecutor - context.original_message: {repr(getattr(context, 'original_message', 'NOT SET'))}")
        logger.debug(f"IdentityExtractorExecutor - context.name: {getattr(context, 'name', None)}, vorname: {getattr(context, 'vorname', None)}, email: {getattr(context, 'email', None)}")
        
        # Ensure original_message exists - it should be set by IntakeExecutor
        if not hasattr(context, 'original_message') or not context.original_message:
            logger.warning(f"IdentityExtractorExecutor - original_message is missing or empty!")
            # If original_message is missing, we can't extract - pass through
            await ctx.send_message(context)
            return
        
        # Check if message contains separator (---) indicating identity was provided in follow-up
        # Format: "{original_message}\n\n---\n{identity_message}"
        # In this case, we should extract identity ONLY from the part after the separator
        full_message = context.original_message
        identity_text = full_message
        separator = "\n\n---\n"
        
        if separator in full_message:
            # Split on separator and extract identity from the part after it
            parts = full_message.split(separator, 1)
            if len(parts) == 2:
                identity_text = parts[1].strip()
                logger.debug(f"IdentityExtractorExecutor - detected separator, extracting from identity part: {repr(identity_text)}")
                # Keep the full message in original_message for classification, but extract from identity_text
            else:
                # Malformed separator, use full message
                logger.warning(f"IdentityExtractorExecutor - malformed separator, using full message")
                identity_text = full_message
        else:
            # No separator, extract from full message
            logger.debug(f"IdentityExtractorExecutor - no separator, extracting from full message")
            identity_text = full_message
            
        missing = [field for field in ("name", "vorname", "email") if not getattr(context, field)]
        logger.debug(f"IdentityExtractorExecutor - missing fields: {missing}")
        
        if not missing:
            logger.debug("IdentityExtractorExecutor - all fields present, passing through")
            await ctx.send_message(context)
            return

        # Try regex fallback first for strict format "Name, Vorname, Email"
        # This is more reliable than LLM for this specific format
        # Always try regex first, even if we think we have some values
        # Pass identity_text (not full_message) for extraction
        logger.debug(f"IdentityExtractorExecutor - calling _apply_regex_fallback with missing: {missing}")
        self._apply_regex_fallback(context, missing, identity_text)
        
        logger.debug(f"IdentityExtractorExecutor - after regex fallback - name: {context.name}, vorname: {context.vorname}, email: {context.email}")
        
        # Recalculate missing after regex fallback
        missing = [field for field in ("name", "vorname", "email") if not getattr(context, field)]
        logger.debug(f"IdentityExtractorExecutor - still missing after regex: {missing}")

        # If still missing, try LLM extraction
        if missing:
            try:
                logger.debug(f"IdentityExtractorExecutor - trying LLM extraction for missing fields: {missing}")
                # Enhance the prompt with context about what we're looking for
                # Use identity_text (not full_message) for extraction
                extraction_prompt = (
                    f"Extrahiere aus folgendem Text die fehlenden Kontaktdaten: {', '.join(missing)}\n\n"
                    f"Text: {identity_text}\n\n"
                    f"Gib ein JSON mit genau diesen Feldern zurück: {', '.join(missing)}"
                )
                response = await self.agent.run(extraction_prompt)
                parsed = parse_json_response(response.text)
                logger.debug(f"IdentityExtractorExecutor - LLM parsed response: {parsed}")

                for field in missing:
                    value = parsed.get(field)
                    normalized = self._normalize_value(field, value)
                    if normalized:
                        setattr(context, field, normalized)
                        logger.debug(f"IdentityExtractorExecutor - LLM extracted {field}: {normalized}")
            except Exception as e:
                # If LLM extraction fails, continue with what we have from regex
                logger.warning(f"IdentityExtractorExecutor - LLM extraction failed: {e}")

        # Final check: ensure all extracted values are non-empty strings
        for field in ("name", "vorname", "email"):
            value = getattr(context, field)
            if value and not isinstance(value, str):
                setattr(context, field, str(value).strip() or None)
            elif value and isinstance(value, str) and not value.strip():
                setattr(context, field, None)

        logger.debug(f"IdentityExtractorExecutor - final context: name={context.name}, vorname={context.vorname}, email={context.email}")
        await ctx.send_message(context)


    def _normalize_value(self, field: str, value: Any) -> str | None:
        if not value:
            return None
        value = str(value).strip()
        if not value:
            return None
        if field == "email":
            match = self._EMAIL_PATTERN.search(value)
            return match.group(0).lower() if match else None
        return value

    def _apply_regex_fallback(self, context: TicketContext, missing: list[str], text: str | None = None) -> None:
        """Fallback extraction that handles multiple formats:
        - Strict format: "Name, Vorname, E-Mail-Adresse" (comma-separated, exactly 3 parts)
        - Natural language: "mein Name ist Peter Schneider, meine E-Mail ist peter@example.com"
        - Flexible extraction: extracts email and tries to find names in surrounding context
        
        This method handles both initial messages with embedded identity and follow-up messages
        where the user provides identity information after being asked for it.
        
        Args:
            context: The ticket context to update with extracted values
            missing: List of missing field names to extract
            text: The text to extract from. If None, uses context.original_message
        """
        logger = get_logger(__name__)
        
        if not missing:
            logger.debug("_apply_regex_fallback - no missing fields, returning")
            return
        
        # Use provided text or fall back to original_message
        if text is None:
            if not hasattr(context, 'original_message') or not context.original_message:
                logger.warning(f"_apply_regex_fallback - original_message missing: {repr(getattr(context, 'original_message', 'NOT SET'))}")
                return
            text = context.original_message.strip()
        
        text = text.strip()
        logger.debug(f"_apply_regex_fallback - text: {repr(text)}")
        
        if not text:
            logger.debug("_apply_regex_fallback - text is empty after strip")
            return
        
        # Try to extract email first (most reliable identifier)
        email_match = self._extract_email_from_text(context, missing, text)
        
        # Split by comma for format detection
        parts = [p.strip() for p in text.split(",") if p.strip()]
        logger.debug(f"_apply_regex_fallback - parts: {parts}, length: {len(parts)}")
        
        # Try strict format first (exactly 3 comma-separated parts)
        if len(parts) == 3:
            self._extract_from_strict_format(context, missing, parts, logger)
        else:
            # Try natural language patterns, then flexible extraction
            self._extract_from_natural_language(context, missing, text, logger)
            if email_match and (("name" in missing and not context.name) or ("vorname" in missing and not context.vorname)):
                self._extract_from_flexible_format(context, missing, text, email_match.group(0), logger)
        
        logger.debug(f"_apply_regex_fallback - final context: name={context.name}, vorname={context.vorname}, email={context.email}")
    
    def _extract_email_from_text(self, context: TicketContext, missing: list[str], text: str) -> re.Match[str] | None:
        """Extract email from text if missing."""
        if "email" not in missing:
            return None
        
        email_match = self._EMAIL_PATTERN.search(text)
        if email_match:
            context.email = email_match.group(0).lower()
            logger = get_logger(__name__)
            logger.debug(f"_extract_email_from_text - extracted email: {context.email}")
        return email_match
    
    def _extract_from_strict_format(self, context: TicketContext, missing: list[str], parts: list[str], logger: logging.Logger) -> None:
        """Extract from strict format: "Name, Vorname, E-Mail-Adresse"."""
        # Find which part is the email
        email_index = -1
        for i, part in enumerate(parts):
            if self._EMAIL_PATTERN.search(part):
                email_index = i
                break
        
        if email_index < 0:
            logger.debug("_extract_from_strict_format - no email found in parts")
            return
        
        # Extract email if missing
        if "email" in missing and not context.email:
            match = self._EMAIL_PATTERN.search(parts[email_index])
            if match:
                context.email = match.group(0).lower()
                logger.debug(f"_extract_from_strict_format - extracted email: {context.email}")
        
        # Extract names from the other two positions
        name_indices = [i for i in range(3) if i != email_index]
        if len(name_indices) != 2:
            return
        
        # Standard format: first part is name, second is vorname (when email is at position 2)
        if email_index == 2:
            # Format: "Name, Vorname, email@example.com"
            self._set_field_if_missing(context, "name", parts[0], logger)
            self._set_field_if_missing(context, "vorname", parts[1], logger)
        else:
            # Email is at position 0 or 1, names are at the other positions
            self._set_field_if_missing(context, "name", parts[name_indices[0]], logger)
            self._set_field_if_missing(context, "vorname", parts[name_indices[1]], logger)
    
    def _extract_from_natural_language(self, context: TicketContext, missing: list[str], text: str, logger: logging.Logger) -> None:
        """Extract from natural language patterns like 'mein Name ist Peter Schneider'."""
        # Try to extract names using natural language patterns
        for pattern in self._NATURAL_NAME_PATTERNS:
            match = pattern.search(text)
            if match:
                if "vorname" in missing and not context.vorname and match.group("vorname"):
                    context.vorname = match.group("vorname").strip()
                    logger.debug(f"_extract_from_natural_language - extracted vorname: {context.vorname}")
                if "name" in missing and not context.name and match.group("name"):
                    context.name = match.group("name").strip()
                    logger.debug(f"_extract_from_natural_language - extracted name: {context.name}")
                if context.vorname or context.name:
                    break  # Found names, stop trying other patterns
        
        # Try to extract email using natural language patterns (if not already extracted)
        if "email" in missing and not context.email:
            for pattern in self._NATURAL_EMAIL_PATTERNS:
                match = pattern.search(text)
                if match:
                    context.email = match.group("email").lower()
                    logger.debug(f"_extract_from_natural_language - extracted email: {context.email}")
                    break
    
    def _extract_from_flexible_format(self, context: TicketContext, missing: list[str], text: str, email_text: str, logger: logging.Logger) -> None:
        """Extract names from comma-separated parts when email is found but names aren't."""
        # Remove email from text and try to extract names
        text_without_email = text.replace(email_text, "").strip()
        name_parts = [p.strip() for p in text_without_email.split(",") if p.strip()]
        
        if len(name_parts) >= 2:
            # Assume first is name, second is vorname (common German format)
            self._set_field_if_missing(context, "name", name_parts[0], logger)
            if len(name_parts) > 1:
                self._set_field_if_missing(context, "vorname", name_parts[1], logger)
    
    def _set_field_if_missing(self, context: TicketContext, field: str, value: str | None, logger: logging.Logger) -> None:
        """Set a field on context if it's missing and value is valid."""
        if field not in ("name", "vorname"):
            return
        
        if getattr(context, field):
            return  # Already set
        
        if not value or value.isspace():
            return
        
        setattr(context, field, value.strip())
        logger.debug(f"_set_field_if_missing - extracted {field}: {getattr(context, field)}")

