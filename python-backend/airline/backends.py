"""
Backend implementations for simulating Database, Knowledge Base, and MCP services.
All backends use JSON files for easy testing and attack vector injection.
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


DATA_DIR = Path(__file__).parent.parent / "data"


class JSONDatabase:
    """
    JSON file-based database simulator.

    Supports CRUD operations on JSON files that simulate database tables.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or DATA_DIR
        self._cache: dict[str, dict] = {}

    def _get_db_path(self) -> Path:
        return self.base_path / "database"

    def load_table(self, table: str) -> dict:
        """Load a JSON table into cache."""
        if table not in self._cache:
            file_path = self._get_db_path() / f"{table}.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    self._cache[table] = json.load(f)
            else:
                self._cache[table] = {}
        return self._cache[table]

    def save_table(self, table: str) -> None:
        """Save a table back to JSON file."""
        if table in self._cache:
            file_path = self._get_db_path() / f"{table}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self._cache[table], f, ensure_ascii=False, indent=2)

    def query(self, table: str, filters: Optional[dict] = None) -> list[dict]:
        """
        Query records from a table with optional filters.

        Args:
            table: Table name (customers, flights, bookings, seats)
            filters: Dict of field:value pairs for filtering

        Returns:
            List of matching records
        """
        data = self.load_table(table)

        # Handle different table structures
        if table == "seats" or table == "seat_maps":
            return self._query_seats(data, filters)

        records = data.get(table, data.get(list(data.keys())[0] if data else table, []))

        if not filters:
            return records

        results = []
        for record in records:
            match = True
            for key, value in filters.items():
                record_value = record.get(key)
                # Support nested key access with dot notation
                if "." in key:
                    parts = key.split(".")
                    record_value = record
                    for part in parts:
                        if isinstance(record_value, dict):
                            record_value = record_value.get(part)
                        else:
                            record_value = None
                            break

                if record_value != value:
                    match = False
                    break
            if match:
                results.append(record)
        return results

    def _query_seats(self, data: dict, filters: Optional[dict]) -> list[dict]:
        """Special handling for seat_maps structure."""
        seat_maps = data.get("seat_maps", {})

        if filters and "flight_number" in filters:
            flight = filters["flight_number"]
            if flight in seat_maps:
                return [seat_maps[flight]]
            return []

        return list(seat_maps.values())

    def get_by_id(self, table: str, record_id: str, id_field: str = "id") -> Optional[dict]:
        """Get a single record by ID."""
        results = self.query(table, {id_field: record_id})
        return results[0] if results else None

    def update(self, table: str, record_id: str, updates: dict, id_field: str = "id") -> bool:
        """
        Update a record by ID.

        Returns:
            True if record was found and updated, False otherwise
        """
        data = self.load_table(table)
        records = data.get(table, [])

        for record in records:
            if record.get(id_field) == record_id:
                record.update(updates)
                record["updated_at"] = datetime.now().isoformat()
                return True
        return False

    def insert(self, table: str, record: dict) -> str:
        """
        Insert a new record.

        Returns:
            The generated record ID
        """
        data = self.load_table(table)
        if table not in data:
            data[table] = []

        # Generate ID if not provided
        if "id" not in record:
            prefix = table.upper()[:3]
            record["id"] = f"{prefix}{random.randint(1000, 9999)}"

        record["created_at"] = datetime.now().isoformat()
        data[table].append(record)

        return record["id"]

    def delete(self, table: str, record_id: str, id_field: str = "id") -> bool:
        """
        Delete a record by ID.

        Returns:
            True if record was found and deleted, False otherwise
        """
        data = self.load_table(table)
        records = data.get(table, [])

        for i, record in enumerate(records):
            if record.get(id_field) == record_id:
                records.pop(i)
                return True
        return False

    def clear_cache(self):
        """Clear the in-memory cache."""
        self._cache.clear()


class KnowledgeBase:
    """
    Knowledge base simulator with simple keyword-based search.

    In a real system, this would use vector embeddings and semantic search.
    For testing purposes, we use keyword matching with scoring.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or DATA_DIR
        self._docs: dict[str, dict] = {}
        self._loaded = False

    def _get_kb_path(self) -> Path:
        return self.base_path / "knowledge_base"

    def load_all(self) -> None:
        """Load all knowledge base documents."""
        if self._loaded:
            return

        kb_path = self._get_kb_path()
        if not kb_path.exists():
            return

        for file in kb_path.glob("*.json"):
            with open(file, "r", encoding="utf-8") as f:
                self._docs[file.stem] = json.load(f)

        self._loaded = True

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Search knowledge base with keyword matching.

        Args:
            query: Natural language search query
            top_k: Maximum number of results to return

        Returns:
            List of matching documents with scores
        """
        self.load_all()

        query_lower = query.lower()
        query_words = set(query_lower.split())
        results = []

        # Search policies
        for policy in self._docs.get("policies", {}).get("policies", []):
            score = self._score_document(policy, query_lower, query_words, "policy")
            if score > 0:
                results.append({
                    "type": "policy",
                    "score": score,
                    "id": policy.get("id"),
                    "title": policy.get("title"),
                    "content": policy.get("content"),
                    "category": policy.get("category")
                })

        # Search FAQs
        for faq in self._docs.get("faq", {}).get("faqs", []):
            score = self._score_document(faq, query_lower, query_words, "faq")
            if score > 0:
                results.append({
                    "type": "faq",
                    "score": score,
                    "id": faq.get("id"),
                    "question": faq.get("question"),
                    "answer": faq.get("answer"),
                    "category": faq.get("category")
                })

        # Search procedures
        for proc in self._docs.get("procedures", {}).get("procedures", []):
            score = self._score_document(proc, query_lower, query_words, "procedure")
            if score > 0:
                results.append({
                    "type": "procedure",
                    "score": score,
                    "id": proc.get("id"),
                    "name": proc.get("name"),
                    "steps": proc.get("steps"),
                    "required_info": proc.get("required_info")
                })

        # Sort by score and return top_k
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _score_document(
        self,
        doc: dict,
        query_lower: str,
        query_words: set,
        doc_type: str
    ) -> float:
        """Calculate relevance score for a document."""
        score = 0.0

        # Keyword matching (highest weight)
        keywords = doc.get("keywords", [])
        for kw in keywords:
            if kw.lower() in query_lower:
                score += 3.0

        # Title/question matching
        title_field = "title" if doc_type == "policy" else "question" if doc_type == "faq" else "name"
        title = doc.get(title_field, "").lower()
        for word in query_words:
            if len(word) > 2 and word in title:
                score += 2.0

        # Content matching
        content_field = "content" if doc_type == "policy" else "answer" if doc_type == "faq" else "steps"
        content = doc.get(content_field, "")
        if isinstance(content, list):
            content = " ".join(content)
        content = content.lower()

        for word in query_words:
            if len(word) > 2 and word in content:
                score += 1.0

        return score

    def get_by_id(self, doc_type: str, doc_id: str) -> Optional[dict]:
        """Get a specific document by type and ID."""
        self.load_all()

        type_mapping = {
            "policy": ("policies", "policies"),
            "faq": ("faq", "faqs"),
            "procedure": ("procedures", "procedures")
        }

        if doc_type not in type_mapping:
            return None

        file_key, list_key = type_mapping[doc_type]
        docs = self._docs.get(file_key, {}).get(list_key, [])

        for doc in docs:
            if doc.get("id") == doc_id:
                return doc
        return None

    def clear_cache(self):
        """Clear loaded documents."""
        self._docs.clear()
        self._loaded = False


class MCPServiceBridge:
    """
    MCP (Model Context Protocol) service simulator.

    Simulates external service calls like email, payment, and calendar.
    Responses are based on JSON configuration files.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or DATA_DIR
        self._services: dict[str, dict] = {}

    def _get_mcp_path(self) -> Path:
        return self.base_path / "mcp_services"

    def load_service(self, service: str) -> dict:
        """Load a service configuration."""
        if service not in self._services:
            file_path = self._get_mcp_path() / f"{service}_service.json"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    self._services[service] = json.load(f)
            else:
                self._services[service] = {}
        return self._services[service]

    def call(
        self,
        service: str,
        action: str,
        params: Optional[dict] = None
    ) -> dict:
        """
        Call an MCP service action.

        Args:
            service: Service name (email, payment, calendar)
            action: Action to perform (send, charge, refund, etc.)
            params: Parameters for the action

        Returns:
            Response dict with status and data
        """
        config = self.load_service(service)
        actions = config.get("actions", {})

        if action not in actions:
            return {
                "error": True,
                "code": "unknown_action",
                "message": f"Unknown action: {action} for service {service}"
            }

        action_config = actions[action]

        # Check required params
        required = action_config.get("required_params", [])
        params = params or {}
        missing = [p for p in required if p not in params]
        if missing:
            return {
                "error": True,
                "code": "missing_params",
                "message": f"Missing required parameters: {', '.join(missing)}"
            }

        # Generate response from template
        response = self._generate_response(action_config, params)
        return response

    def _generate_response(self, action_config: dict, params: dict) -> dict:
        """Generate response by filling in template variables."""
        template = action_config.get("success_response", {})
        response = {}

        for key, value in template.items():
            if isinstance(value, str):
                response[key] = self._fill_template(value, params)
            else:
                response[key] = value

        return response

    def _fill_template(self, template: str, params: dict) -> str:
        """Fill in template variables."""
        result = template

        # Replace {random} with random string
        if "{random}" in result:
            random_str = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            result = result.replace("{random}", random_str)

        # Replace {now} with current timestamp
        if "{now}" in result:
            result = result.replace("{now}", datetime.now().isoformat())

        # Replace parameter placeholders
        for key, value in params.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))

        return result

    def get_available_services(self) -> list[str]:
        """Get list of available services."""
        mcp_path = self._get_mcp_path()
        if not mcp_path.exists():
            return []

        services = []
        for file in mcp_path.glob("*_service.json"):
            service_name = file.stem.replace("_service", "")
            services.append(service_name)
        return services

    def get_service_actions(self, service: str) -> list[str]:
        """Get available actions for a service."""
        config = self.load_service(service)
        return list(config.get("actions", {}).keys())


# Global instances for convenience
_db: Optional[JSONDatabase] = None
_kb: Optional[KnowledgeBase] = None
_mcp: Optional[MCPServiceBridge] = None


def get_database() -> JSONDatabase:
    """Get the global database instance."""
    global _db
    if _db is None:
        _db = JSONDatabase()
    return _db


def get_knowledge_base() -> KnowledgeBase:
    """Get the global knowledge base instance."""
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


def get_mcp_bridge() -> MCPServiceBridge:
    """Get the global MCP bridge instance."""
    global _mcp
    if _mcp is None:
        _mcp = MCPServiceBridge()
    return _mcp


def reset_backends():
    """Reset all backend instances (useful for testing)."""
    global _db, _kb, _mcp
    if _db:
        _db.clear_cache()
    if _kb:
        _kb.clear_cache()
    _db = None
    _kb = None
    _mcp = None
