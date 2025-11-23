import json
import re
from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.schemas import TicketContext, TicketResponse

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
        import logging
        logger = logging.getLogger(__name__)
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
                parsed = self._parse_response(response.text)
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

    def _parse_response(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                fragment = text[start : end + 1]
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError:
                    return {}
        return {}

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
        import logging
        logger = logging.getLogger(__name__)
        
        if not missing:
            logger.debug("_apply_regex_fallback - no missing fields, returning")
            return
        
        # Use provided text or fall back to original_message
        if text is None:
            # Ensure we have original_message - it should always be set by IntakeExecutor
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
        email_match = self._EMAIL_PATTERN.search(text)
        if email_match and "email" in missing:
            extracted_email = email_match.group(0).lower()
            context.email = extracted_email
            logger.debug(f"_apply_regex_fallback - extracted email: {extracted_email}")
        
        # Only accept strict comma-separated format: "Name, Vorname, E-Mail-Adresse"
        # Split by comma and strip whitespace, filter out empty parts
        parts = [p.strip() for p in text.split(",") if p.strip()]
        logger.debug(f"_apply_regex_fallback - parts: {parts}, length: {len(parts)}")
        
        # Must have exactly 3 comma-separated parts for strict format extraction
        if len(parts) != 3:
            logger.debug(f"_apply_regex_fallback - not exactly 3 parts, trying natural language patterns")
            # Try natural language patterns for German phrases
            # First, try to extract names using natural language patterns
            for pattern in self._NATURAL_NAME_PATTERNS:
                match = pattern.search(text)
                if match:
                    if "vorname" in missing and not context.vorname and match.group("vorname"):
                        context.vorname = match.group("vorname").strip()
                        logger.debug(f"_apply_regex_fallback - extracted vorname (natural): {context.vorname}")
                    if "name" in missing and not context.name and match.group("name"):
                        context.name = match.group("name").strip()
                        logger.debug(f"_apply_regex_fallback - extracted name (natural): {context.name}")
                    if context.vorname or context.name:
                        break  # Found names, stop trying other patterns
            
            # Try to extract email using natural language patterns (if not already extracted)
            if "email" in missing and not context.email:
                for pattern in self._NATURAL_EMAIL_PATTERNS:
                    match = pattern.search(text)
                    if match:
                        extracted_email = match.group("email").lower()
                        context.email = extracted_email
                        logger.debug(f"_apply_regex_fallback - extracted email (natural): {extracted_email}")
                        break
            
            # If we still don't have names but have email, try flexible extraction from comma-separated parts
            if email_match and (("name" in missing and not context.name) or ("vorname" in missing and not context.vorname)):
                email_text = email_match.group(0)
                # Remove email from text and try to extract names
                text_without_email = text.replace(email_text, "").strip()
                # Try to find names in the remaining text
                name_parts = [p.strip() for p in text_without_email.split(",") if p.strip()]
                if len(name_parts) >= 2:
                    # Assume first is name, second is vorname (common German format)
                    if "name" in missing and not context.name and name_parts[0]:
                        context.name = name_parts[0]
                        logger.debug(f"_apply_regex_fallback - extracted name (flexible): {context.name}")
                    if "vorname" in missing and not context.vorname and len(name_parts) > 1 and name_parts[1]:
                        context.vorname = name_parts[1]
                        logger.debug(f"_apply_regex_fallback - extracted vorname (flexible): {context.vorname}")
            
            logger.debug(f"_apply_regex_fallback - final context after natural/flexible: name={context.name}, vorname={context.vorname}, email={context.email}")
            return
        
        # Find which part is the email
        email_index = -1
        for i, part in enumerate(parts):
            if self._EMAIL_PATTERN.search(part):
                email_index = i
                break
        
        logger.debug(f"_apply_regex_fallback - email_index: {email_index}")
        
        if email_index < 0:
            # No email found, can't extract with strict format
            logger.debug("_apply_regex_fallback - no email found in parts")
            return
        
        # Email found, extract it (if not already extracted)
        if "email" in missing and not context.email:
            match = self._EMAIL_PATTERN.search(parts[email_index])
            if match:
                extracted_email = match.group(0).lower()
                context.email = extracted_email
                logger.debug(f"_apply_regex_fallback - extracted email: {extracted_email}")
        
        # Extract names from the other two positions
        name_indices = [i for i in range(3) if i != email_index]
        if len(name_indices) != 2:
            return
        
        # Standard format: first part is name, second is vorname (when email is at position 2)
        if email_index == 2:
            # Format: "Name, Vorname, email@example.com"
            if "name" in missing and not context.name:
                name_val = parts[0].strip() if parts[0] else ""
                if name_val and not name_val.isspace():
                    context.name = name_val
                    logger.debug(f"_apply_regex_fallback - extracted name: {name_val}")
            if "vorname" in missing and not context.vorname:
                vorname_val = parts[1].strip() if parts[1] else ""
                if vorname_val and not vorname_val.isspace():
                    context.vorname = vorname_val
                    logger.debug(f"_apply_regex_fallback - extracted vorname: {vorname_val}")
        else:
            # Email is at position 0 or 1, names are at the other positions
            # Assume first non-email part is name, second is vorname
            if "name" in missing and not context.name:
                name_val = parts[name_indices[0]].strip() if parts[name_indices[0]] else ""
                if name_val and not name_val.isspace():
                    context.name = name_val
                    logger.debug(f"_apply_regex_fallback - extracted name: {name_val}")
            if "vorname" in missing and not context.vorname:
                vorname_val = parts[name_indices[1]].strip() if parts[name_indices[1]] else ""
                if vorname_val and not vorname_val.isspace():
                    context.vorname = vorname_val
                    logger.debug(f"_apply_regex_fallback - extracted vorname: {vorname_val}")
        
        logger.debug(f"_apply_regex_fallback - final context: name={context.name}, vorname={context.vorname}, email={context.email}")

