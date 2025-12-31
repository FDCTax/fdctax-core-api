"""
Email Template Engine - Template Rendering and Validation

This module provides:
- Template rendering with placeholder replacement
- Nested variable support ({{client.address.street}})
- Default values ({{client_name | default:"Client"}})
- HTML sanitization
- Variable validation
"""

import re
import html
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ==================== TEMPLATE REGISTRY ====================

TEMPLATE_VARIABLES = {
    "welcome": {
        "required": ["client_name", "portal_url"],
        "optional": ["year", "company_name"],
        "description": "Welcome email for new clients"
    },
    "appointment_reminder": {
        "required": ["client_name", "date", "time", "location"],
        "optional": ["notes", "contact_phone"],
        "description": "Appointment reminder notification"
    },
    "document_request": {
        "required": ["client_name", "document_name"],
        "optional": ["due_date", "instructions"],
        "description": "Request documents from client"
    },
    "tax_return_ready": {
        "required": ["client_name", "tax_year", "amount"],
        "optional": ["due_date", "portal_url"],
        "description": "Tax return completion notification"
    },
    "invoice": {
        "required": ["client_name", "invoice_number", "amount", "due_date"],
        "optional": ["description", "payment_link"],
        "description": "Invoice email"
    },
    "test": {
        "required": ["timestamp"],
        "optional": [],
        "description": "Test email template"
    },
    "bas_reminder": {
        "required": ["client_name", "period", "due_date"],
        "optional": ["amount_estimate"],
        "description": "BAS lodgement reminder"
    },
    "payment_receipt": {
        "required": ["client_name", "amount", "receipt_number", "payment_date"],
        "optional": ["description", "balance"],
        "description": "Payment receipt confirmation"
    }
}


# ==================== DATA CLASSES ====================

@dataclass
class TemplateValidationResult:
    """Result of template variable validation"""
    valid: bool
    missing: List[str]
    unused: List[str]
    invalid: List[str]
    errors: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "missing": self.missing,
            "unused": self.unused,
            "invalid": self.invalid,
            "errors": self.errors
        }


@dataclass
class RenderResult:
    """Result of template rendering"""
    success: bool
    html: Optional[str] = None
    subject: Optional[str] = None
    error: Optional[str] = None
    validation: Optional[TemplateValidationResult] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "success": self.success,
            "html": self.html,
            "subject": self.subject,
            "error": self.error
        }
        if self.validation:
            result["validation"] = self.validation.to_dict()
        return result


# ==================== TEMPLATE ENGINE ====================

class TemplateEngine:
    """
    Email Template Rendering Engine.
    
    Features:
    - Placeholder replacement: {{variable}}
    - Nested variables: {{client.address.street}}
    - Default values: {{name | default:"Guest"}}
    - Conditional blocks: {{#if variable}}...{{/if}}
    - HTML sanitization
    """
    
    # Regex patterns
    PLACEHOLDER_PATTERN = re.compile(r'\{\{([^}]+)\}\}')
    DEFAULT_PATTERN = re.compile(r'^([^|]+)\s*\|\s*default\s*:\s*["\']([^"\']*)["\']$')
    NESTED_VAR_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$')
    INVALID_VAR_PATTERN = re.compile(r'\.{2,}|^\.|\.$')
    
    # Unsafe HTML tags to remove
    UNSAFE_TAGS = ['script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'select', 'textarea']
    UNSAFE_ATTRS = ['onclick', 'onload', 'onerror', 'onmouseover', 'onfocus', 'onblur', 'onsubmit', 'onchange']
    
    def __init__(self):
        self.strict_mode = False  # If True, raises on missing variables
    
    def render(
        self,
        template: str,
        variables: Dict[str, Any],
        strict: bool = False
    ) -> RenderResult:
        """
        Render a template with variables.
        
        Args:
            template: HTML template with {{placeholders}}
            variables: Dictionary of variable values
            strict: If True, fail on missing variables
            
        Returns:
            RenderResult with rendered HTML or error
        """
        if not template:
            return RenderResult(success=False, error="Template is empty")
        
        # Validate variables first
        validation = self.validate_variables(template, variables)
        
        if strict and not validation.valid:
            return RenderResult(
                success=False,
                error=f"Missing required variables: {', '.join(validation.missing)}",
                validation=validation
            )
        
        try:
            # Render the template
            rendered = self._render_placeholders(template, variables)
            
            # Sanitize HTML
            sanitized = self.sanitize_html(rendered)
            
            return RenderResult(
                success=True,
                html=sanitized,
                validation=validation
            )
            
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            return RenderResult(
                success=False,
                error=str(e),
                validation=validation
            )
    
    def render_with_subject(
        self,
        subject_template: str,
        body_template: str,
        variables: Dict[str, Any],
        strict: bool = False
    ) -> RenderResult:
        """
        Render both subject and body templates.
        
        Args:
            subject_template: Subject line template
            body_template: HTML body template
            variables: Dictionary of variable values
            strict: If True, fail on missing variables
            
        Returns:
            RenderResult with rendered subject and HTML
        """
        # Combine templates for validation
        combined = subject_template + " " + body_template
        validation = self.validate_variables(combined, variables)
        
        if strict and not validation.valid:
            return RenderResult(
                success=False,
                error=f"Missing required variables: {', '.join(validation.missing)}",
                validation=validation
            )
        
        try:
            # Render subject (no HTML sanitization needed)
            rendered_subject = self._render_placeholders(subject_template, variables)
            # Escape HTML entities in subject
            rendered_subject = html.escape(rendered_subject) if rendered_subject else ""
            # Unescape to restore normal text
            rendered_subject = html.unescape(rendered_subject)
            
            # Render body
            rendered_body = self._render_placeholders(body_template, variables)
            sanitized_body = self.sanitize_html(rendered_body)
            
            return RenderResult(
                success=True,
                subject=rendered_subject,
                html=sanitized_body,
                validation=validation
            )
            
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            return RenderResult(
                success=False,
                error=str(e),
                validation=validation
            )
    
    def _render_placeholders(self, template: str, variables: Dict[str, Any]) -> str:
        """Replace all placeholders with values."""
        
        def replace_match(match):
            placeholder = match.group(1).strip()
            return self._resolve_placeholder(placeholder, variables)
        
        return self.PLACEHOLDER_PATTERN.sub(replace_match, template)
    
    def _resolve_placeholder(self, placeholder: str, variables: Dict[str, Any]) -> str:
        """
        Resolve a single placeholder.
        
        Supports:
        - Simple: {{name}}
        - Nested: {{client.address.city}}
        - Default: {{name | default:"Guest"}}
        """
        # Check for default value syntax
        default_match = self.DEFAULT_PATTERN.match(placeholder)
        if default_match:
            var_name = default_match.group(1).strip()
            default_value = default_match.group(2)
            value = self._get_nested_value(var_name, variables)
            return str(value) if value is not None else default_value
        
        # Standard variable lookup
        value = self._get_nested_value(placeholder, variables)
        
        if value is None:
            # Return empty string for missing variables (non-strict mode)
            return ""
        
        return str(value)
    
    def _get_nested_value(self, path: str, data: Dict[str, Any]) -> Any:
        """
        Get a value from nested dictionary using dot notation.
        
        Example: "client.address.city" -> data["client"]["address"]["city"]
        """
        parts = path.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return None
            
            if current is None:
                return None
        
        return current
    
    def validate_variables(
        self,
        template: str,
        variables: Dict[str, Any]
    ) -> TemplateValidationResult:
        """
        Validate variables against template placeholders.
        
        Returns:
            TemplateValidationResult with missing, unused, and invalid variables
        """
        # Extract all placeholders
        placeholders = self.extract_placeholders(template)
        
        # Get provided variable names (including nested paths)
        provided = self._flatten_variables(variables)
        
        # Check for missing variables
        missing = []
        for placeholder in placeholders:
            # Handle default value syntax
            var_name = placeholder
            default_match = self.DEFAULT_PATTERN.match(placeholder)
            if default_match:
                var_name = default_match.group(1).strip()
            
            # Check if variable is provided
            if not self._is_variable_provided(var_name, provided, variables):
                # Skip if it has a default value
                if not default_match:
                    missing.append(var_name)
        
        # Check for unused variables (top-level only)
        used_vars = set()
        for placeholder in placeholders:
            var_name = placeholder
            default_match = self.DEFAULT_PATTERN.match(placeholder)
            if default_match:
                var_name = default_match.group(1).strip()
            # Get root variable name
            root_var = var_name.split('.')[0]
            used_vars.add(root_var)
        
        unused = [v for v in variables.keys() if v not in used_vars]
        
        # Check for invalid variable names
        invalid = []
        for placeholder in placeholders:
            var_name = placeholder
            default_match = self.DEFAULT_PATTERN.match(placeholder)
            if default_match:
                var_name = default_match.group(1).strip()
            
            if self.INVALID_VAR_PATTERN.search(var_name):
                invalid.append(var_name)
            elif not self.NESTED_VAR_PATTERN.match(var_name):
                # Check for invalid characters
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.\s|:"\']*$', placeholder):
                    invalid.append(placeholder)
        
        # Build errors list
        errors = []
        if missing:
            errors.append(f"Missing variables: {', '.join(missing)}")
        if invalid:
            errors.append(f"Invalid variable names: {', '.join(invalid)}")
        
        return TemplateValidationResult(
            valid=len(missing) == 0 and len(invalid) == 0,
            missing=missing,
            unused=unused,
            invalid=invalid,
            errors=errors
        )
    
    def extract_placeholders(self, template: str) -> List[str]:
        """Extract all placeholder names from template."""
        matches = self.PLACEHOLDER_PATTERN.findall(template)
        return [m.strip() for m in matches]
    
    def _flatten_variables(self, variables: Dict[str, Any], prefix: str = "") -> Set[str]:
        """Flatten nested variables into dot notation paths."""
        paths = set()
        
        for key, value in variables.items():
            full_path = f"{prefix}.{key}" if prefix else key
            paths.add(full_path)
            
            if isinstance(value, dict):
                paths.update(self._flatten_variables(value, full_path))
        
        return paths
    
    def _is_variable_provided(
        self,
        var_name: str,
        flat_vars: Set[str],
        original_vars: Dict[str, Any]
    ) -> bool:
        """Check if a variable (including nested) is provided."""
        # Direct match
        if var_name in flat_vars:
            return True
        
        # Check nested lookup
        value = self._get_nested_value(var_name, original_vars)
        return value is not None
    
    def sanitize_html(self, html_content: str) -> str:
        """
        Sanitize HTML content by removing unsafe elements.
        
        Removes:
        - Script tags and content
        - Event handlers (onclick, etc.)
        - Iframe, object, embed tags
        - Form elements
        """
        if not html_content:
            return ""
        
        result = html_content
        
        # Remove unsafe tags and their content
        for tag in self.UNSAFE_TAGS:
            # Remove opening and closing tags with content
            pattern = re.compile(f'<{tag}[^>]*>.*?</{tag}>', re.IGNORECASE | re.DOTALL)
            result = pattern.sub('', result)
            # Remove self-closing tags
            pattern = re.compile(f'<{tag}[^>]*/>', re.IGNORECASE)
            result = pattern.sub('', result)
            # Remove opening tags without closing
            pattern = re.compile(f'<{tag}[^>]*>', re.IGNORECASE)
            result = pattern.sub('', result)
        
        # Remove unsafe attributes
        for attr in self.UNSAFE_ATTRS:
            pattern = re.compile(f'{attr}\\s*=\\s*["\'][^"\']*["\']', re.IGNORECASE)
            result = pattern.sub('', result)
            # Handle unquoted attributes
            pattern = re.compile(f'{attr}\\s*=\\s*[^\\s>]+', re.IGNORECASE)
            result = pattern.sub('', result)
        
        # Remove javascript: URLs
        result = re.sub(r'href\s*=\s*["\']javascript:[^"\']*["\']', 'href="#"', result, flags=re.IGNORECASE)
        result = re.sub(r'src\s*=\s*["\']javascript:[^"\']*["\']', 'src="#"', result, flags=re.IGNORECASE)
        
        return result
    
    def get_template_info(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a registered template."""
        return TEMPLATE_VARIABLES.get(template_id)
    
    def list_templates(self) -> Dict[str, Dict[str, Any]]:
        """List all registered templates with their variable requirements."""
        return TEMPLATE_VARIABLES.copy()


# Global engine instance
_template_engine: Optional[TemplateEngine] = None


def get_template_engine() -> TemplateEngine:
    """Get or create the template engine singleton."""
    global _template_engine
    if _template_engine is None:
        _template_engine = TemplateEngine()
    return _template_engine


# Convenience function
def render_template(template_html: str, variables: dict) -> str:
    """
    Render a template with variables.
    
    Args:
        template_html: HTML template with {{placeholders}}
        variables: Dictionary of variable values
        
    Returns:
        Rendered HTML string
        
    Raises:
        ValueError: If rendering fails
    """
    engine = get_template_engine()
    result = engine.render(template_html, variables)
    
    if not result.success:
        raise ValueError(result.error or "Template rendering failed")
    
    return result.html or ""
