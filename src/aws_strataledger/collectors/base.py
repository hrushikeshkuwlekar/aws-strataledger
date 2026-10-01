"""
Base collector with pagination, retry, and error handling.

All service collectors inherit from BaseCollector.
"""

import time
import logging
from abc import ABC, abstractmethod

import boto3
import botocore.exceptions

logger = logging.getLogger("aws_strataledger")


class BaseCollector(ABC):
    """
    Abstract base collector for AWS service resources.

    Provides:
    - Automatic pagination via _paginate()
    - Safe API calls with retry and error handling via _safe_call()
    - Consistent error reporting
    """

    SERVICE_NAME: str = "unknown"  # Override in subclasses

    def __init__(self, session: boto3.Session, region: str, account_id: str):
        self.session = session
        self.region = region
        self.account_id = account_id
        self._errors: list[str] = []
        self._warnings: list[str] = []

    def _get_client(self, service_name: str):
        """Create a boto3 client for the given service."""
        return self.session.client(service_name, region_name=self.region)

    def _paginate(self, client, method: str, result_key: str, **kwargs) -> list:
        """
        Generic paginator wrapper. Automatically uses boto3 paginators
        when available, falls back to manual pagination.

        Args:
            client: boto3 client
            method: API method name (e.g., 'describe_instances')
            result_key: Key in response containing the result list
            **kwargs: Additional arguments to pass to the API call
        """
        try:
            paginator = client.get_paginator(method)
            results = []
            for page in paginator.paginate(**kwargs):
                # Handle nested keys like 'Reservations' -> 'Instances'
                if "." in result_key:
                    keys = result_key.split(".")
                    items = page
                    for k in keys:
                        if isinstance(items, list):
                            nested = []
                            for item in items:
                                nested.extend(item.get(k, []))
                            items = nested
                        else:
                            items = items.get(k, [])
                    results.extend(items if isinstance(items, list) else [items])
                else:
                    results.extend(page.get(result_key, []))
            return results
        except botocore.exceptions.OperationNotPageableError:
            # Fallback: single API call
            response = getattr(client, method)(**kwargs)
            return response.get(result_key, [])

    def _safe_call(self, func, *args, default=None, **kwargs):
        """
        Wrap an API call with comprehensive error handling and retry logic.

        Returns the function result on success, or `default` on failure.
        """
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)

            except botocore.exceptions.ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]

                if error_code in ("AccessDenied", "AccessDeniedException",
                                  "UnauthorizedAccess", "AuthorizationError"):
                    self._warnings.append(
                        f"[{self.SERVICE_NAME}] Access denied: {error_msg}"
                    )
                    logger.debug(f"Access denied for {self.SERVICE_NAME} in {self.region}: {error_msg}")
                    return default

                elif error_code in ("Throttling", "ThrottlingException",
                                    "TooManyRequestsException", "RequestLimitExceeded"):
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.debug(
                            f"Throttled on {self.SERVICE_NAME} in {self.region}, "
                            f"retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        self._warnings.append(
                            f"[{self.SERVICE_NAME}] Throttled after {max_retries} retries"
                        )
                        return default

                elif error_code in ("InvalidAction", "UnknownOperationException",
                                    "UnsupportedOperation"):
                    # Service/action not available in this region
                    logger.debug(
                        f"{self.SERVICE_NAME} operation not available in {self.region}"
                    )
                    return default

                else:
                    self._errors.append(
                        f"[{self.SERVICE_NAME}] ClientError ({error_code}): {error_msg}"
                    )
                    logger.debug(
                        f"ClientError in {self.SERVICE_NAME}/{self.region}: "
                        f"{error_code} - {error_msg}"
                    )
                    return default

            except botocore.exceptions.EndpointConnectionError:
                logger.debug(
                    f"{self.SERVICE_NAME} endpoint not available in {self.region}"
                )
                return default

            except botocore.exceptions.NoRegionError:
                self._errors.append(f"[{self.SERVICE_NAME}] No region specified")
                return default

            except Exception as e:
                self._errors.append(
                    f"[{self.SERVICE_NAME}] Unexpected error: {type(e).__name__}: {e}"
                )
                logger.debug(
                    f"Unexpected error in {self.SERVICE_NAME}/{self.region}: {e}",
                    exc_info=True,
                )
                return default

        return default

    def _safe_paginate(self, client, method: str, result_key: str, **kwargs) -> list:
        """Combine safe_call with pagination."""
        result = self._safe_call(
            self._paginate, client, method, result_key, default=[], **kwargs
        )
        return result if result is not None else []

    def _extract_tags(self, resource: dict) -> dict[str, str]:
        """Extract tags from a resource into a simple dict."""
        tags = resource.get("Tags") or resource.get("tags") or []
        return {t.get("Key", ""): t.get("Value", "") for t in tags if isinstance(t, dict)}

    def _get_name_tag(self, resource: dict) -> str:
        """Get the 'Name' tag value from a resource."""
        tags = self._extract_tags(resource)
        return tags.get("Name", "")

    @abstractmethod
    def collect(self) -> dict:
        """
        Collect all resources for this service category.

        Returns:
            dict mapping resource_type_name -> list of resource dicts
        """
        ...

    def get_errors(self) -> list[str]:
        """Return collected errors."""
        return self._errors

    def get_warnings(self) -> list[str]:
        """Return collected warnings."""
        return self._warnings
