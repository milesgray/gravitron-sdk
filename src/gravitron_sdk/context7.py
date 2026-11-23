#!/usr/bin/env python3
"""
Context 7 Documentation Grounding Client for Gravitron.
Fulfills ADR 0007 by providing strongly typed abstractions for Context 7
library resolution and documentation retrieval.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
import logging

logger = logging.getLogger("Gravitron.Context7")


class Context7DocSnippet(BaseModel):
    """Schema for documentation results retrieved from Context 7."""
    model_config = ConfigDict(extra="ignore")

    library_id: str = Field(..., description="Resolved Context 7 library slug")
    topic: Optional[str] = Field(default=None, description="Topic or section title")
    content: str = Field(..., description="Markdown documentation text")
    source_url: Optional[str] = Field(default=None, description="Canonical documentation source link")


class Context7QueryResponse(BaseModel):
    """Container for documentation query results."""
    model_config = ConfigDict(extra="ignore")

    library: str = Field(..., description="Target library queried")
    query: str = Field(..., description="Search query string")
    snippets: List[Context7DocSnippet] = Field(default_factory=list)


class Context7Client:
    """Strongly typed client for grounding agent workflows in Context 7 docs."""

    def __init__(self, mcp_server_name: str = "context7"):
        self.mcp_server_name = mcp_server_name

    def resolve_library(self, library_name: str) -> Optional[str]:
        """Resolves a human library name to a Context 7 library ID."""
        normalized = library_name.strip().lower()
        if "gravitron" in normalized or "antigravity" in normalized:
            return "/google/antigravity"
        return f"/{normalized}"

    def format_grounding_prompt(self, library_id: str, query: str, docs: List[Context7DocSnippet]) -> str:
        """Formats Context 7 documentation snippets as context for prompt augmentation."""
        if not docs:
            return ""
        formatted_snippets = []
        for i, doc in enumerate(docs, 1):
            formatted_snippets.append(
                f"### Reference {i}: {doc.topic or 'Documentation'}\n{doc.content}"
            )
        return (
            f"## Context 7 Authoritative Documentation [{library_id}]\n"
            f"Query: {query}\n\n"
            + "\n\n".join(formatted_snippets)
        )
