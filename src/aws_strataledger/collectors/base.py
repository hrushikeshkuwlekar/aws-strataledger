from __future__ import annotations

"""
Base collector with pagination, error classification, and issue reporting.

All service collectors inherit from BaseCollector. Retries and throttling are
handled by botocore (adaptive retry mode, see ``session.BOTO_CONFIG``); this
class only classifies failures and records them as *issues* so the report can
show exactly which data could not be collected.
"""

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

import botocore.exceptions

logger = logging.getLogger("aws_strataledger")

ACCESS_DENIED_CODES = frozenset({
    "AccessDenied", "AccessDeniedException", "UnauthorizedOperation",
    "UnauthorizedAccess", "AuthorizationError", "AuthorizationErrorException",
    "Forbidden", "ForbiddenException",
})

# Service or operation not offered / not enabled in this region or account.
UNAVAILABLE_CODES = frozenset({
    "InvalidAction", "UnknownOperationException", "UnsupportedOperation",
    "OptInRequired", "SubscriptionRequiredException", "UnrecognizedClientException",
    "AuthFailure", "InvalidClientTokenId",
})

THROTTLING_CODES = frozenset({
    "Throttling", "ThrottlingException", "TooManyRequestsException",
    "RequestLimitExceeded", "SlowDown",
})

# Issue levels, most to least severe.
LEVEL_ERROR = "error"
LEVEL_DENIED = "denied"
LEVEL_UNAVAILABLE = "unavailable"


class BaseCollector(ABC):
    """
    Abstract base collector for AWS service resources.

    Provides:
    - Pagination via _paginate() (botocore paginators) and _paginate_tokens()
      (manual NextToken/NextMarker loops for APIs without paginators)
    - Safe API calls via _safe_call() that classify failures into issues
    - _parallel() for bounded fan-out of per-resource detail calls

    Result convention: ``collect()`` returns ``{resource_key: [resource dicts]}``.
    Keys starting with ``_`` hold metadata (not resources) and are excluded from
    counts and the inventory table.
    """

    SERVICE_NAME: str = "unknown"  # Override in subclasses

    def __init__(self, clients, region: str, account_id: str):
        self.clients = clients
        self.region = region
        self.account_id = account_id
        self._issues: list[dict] = []

    # ── Clients ──────────────────────────────────────────────────────

    def _get_client(self, service_name: str, region: str | None = None):
        """Return a shared, thread-safe boto3 client for the service."""
        return self.clients.get(service_name, region or self.region)

    # ── Pagination ───────────────────────────────────────────────────

    def _paginate(self, client, method: str, result_key: str,
                  max_items: int | None = None, **kwargs) -> list:
        """
        Paginate with the botocore paginator for ``method``.

        ``result_key`` may be dotted (e.g. ``Reservations.Instances``) to flatten
        nested lists. Falls back to a single call when the operation is not pageable.
        """
        if not client.can_paginate(method):
            response = getattr(client, method)(**kwargs)
            return _extract(response, result_key)
        if max_items:
            kwargs["PaginationConfig"] = {"MaxItems": max_items}
        results: list = []
        for page in client.get_paginator(method).paginate(**kwargs):
            results.extend(_extract(page, result_key))
        return results

    def _paginate_tokens(self, client, method: str, result_key: str,
                         token_in: str = "NextToken", token_out: str | None = None,
                         max_pages: int = 100, **kwargs) -> list:
        """Manual pagination for operations that botocore has no paginator for."""
        token_out = token_out or token_in
        results: list = []
        for _ in range(max_pages):
            response = getattr(client, method)(**kwargs)
            results.extend(_extract(response, result_key))
            token = response.get(token_out)
            if not token:
                break
            kwargs[token_in] = token
        return results

    # ── Safe calls & issue recording ─────────────────────────────────

    def _safe_call(self, func: Callable, *args, default=None,
                   ignore: Iterable[str] = (), **kwargs):
        """
        Call ``func`` and return its result, or ``default`` on failure.

        ``ignore`` lists error codes that mean "not configured" (for example
        ``NoSuchBucketPolicy``); they return ``default`` without recording an issue.
        """
        try:
            return func(*args, **kwargs)
        except botocore.exceptions.ClientError as e:
            error = e.response.get("Error", {})
            code = error.get("Code", "Unknown")
            message = error.get("Message", str(e))
            if code in ignore:
                return default
            operation = getattr(e, "operation_name", None) or _func_name(func)
            if code in ACCESS_DENIED_CODES:
                level = LEVEL_DENIED
            elif code in UNAVAILABLE_CODES:
                level = LEVEL_UNAVAILABLE
            elif code in THROTTLING_CODES:
                level, message = LEVEL_ERROR, f"Throttled after retries: {message}"
            else:
                level = LEVEL_ERROR
            self._record(level, operation, code, message)
            return default
        except botocore.exceptions.EndpointConnectionError as e:
            self._record(LEVEL_UNAVAILABLE, _func_name(func), "EndpointConnectionError", str(e))
            return default
        except botocore.exceptions.ParamValidationError as e:
            self._record(LEVEL_ERROR, _func_name(func), "ParamValidationError", str(e))
            return default
        except Exception as e:  # noqa: BLE001 — isolate every collector failure
            logger.debug("Unexpected error in %s/%s", self.SERVICE_NAME, self.region, exc_info=True)
            self._record(LEVEL_ERROR, _func_name(func), type(e).__name__, str(e))
            return default

    def _safe_paginate(self, client, method: str, result_key: str,
                       ignore: Iterable[str] = (), max_items: int | None = None,
                       **kwargs) -> list:
        """Paginate with error handling; always returns a list."""
        result = self._safe_call(
            self._paginate, client, method, result_key,
            default=[], ignore=ignore, max_items=max_items, **kwargs,
        )
        return result if result is not None else []

    def _safe_paginate_tokens(self, client, method: str, result_key: str,
                              ignore: Iterable[str] = (), **kwargs) -> list:
        result = self._safe_call(
            self._paginate_tokens, client, method, result_key,
            default=[], ignore=ignore, **kwargs,
        )
        return result if result is not None else []

    def _record(self, level: str, operation: str, code: str, message: str):
        logger.debug("[%s/%s] %s %s: %s", self.SERVICE_NAME, self.region, operation, code, message)
        self._issues.append({
            "collector": self.SERVICE_NAME,
            "region": self.region,
            "operation": operation,
            "code": code,
            "level": level,
            "message": (message or "")[:500],
        })

    # ── Helpers ──────────────────────────────────────────────────────

    def _parallel(self, func: Callable[[Any], Any], items: list, max_workers: int = 8) -> list:
        """Map ``func`` over ``items`` with bounded concurrency, preserving order."""
        if len(items) <= 1:
            return [func(i) for i in items]
        with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
            return list(pool.map(func, items))

    def _extract_tags(self, resource: dict) -> dict[str, str]:
        """Extract tags from a resource into a simple dict."""
        tags = resource.get("Tags") or resource.get("tags") or resource.get("TagList") or []
        if isinstance(tags, dict):
            return dict(tags)
        # Most services use Key/Value; ECS and a few others use key/value.
        return {
            t.get("Key", t.get("key", "")): t.get("Value", t.get("value", ""))
            for t in tags if isinstance(t, dict)
        }

    def _get_name_tag(self, resource: dict) -> str:
        """Get the 'Name' tag value from a resource."""
        return self._extract_tags(resource).get("Name", "")

    @abstractmethod
    def collect(self) -> dict:
        """
        Collect all resources for this service category.

        Returns:
            dict mapping resource_type_name -> list of resource dicts
        """

    def get_issues(self) -> list[dict]:
        """Return recorded collection issues."""
        return self._issues


def _extract(page: dict, result_key: str) -> list:
    """Pull ``result_key`` (optionally dotted) out of a response page as a flat list."""
    items: Any = page
    for key in result_key.split("."):
        if isinstance(items, list):
            nested: list = []
            for item in items:
                value = item.get(key, [])
                nested.extend(value if isinstance(value, list) else [value])
            items = nested
        else:
            items = (items or {}).get(key, [])
    if items is None:
        return []
    return items if isinstance(items, list) else [items]


def _func_name(func: Callable) -> str:
    name = getattr(func, "__name__", "call")
    return "call" if name == "<lambda>" else name


def chunks(items: list, size: int) -> Iterable[list]:
    """Yield successive ``size``-sized chunks of ``items``."""
    for i in range(0, len(items), size):
        yield items[i:i + size]
