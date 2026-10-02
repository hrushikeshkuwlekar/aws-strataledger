from __future__ import annotations

"""
AWS SSO session management.

Creates and validates boto3 sessions from SSO profiles,
handles token expiry and access errors gracefully, and hands out
thread-safe, cached boto3 clients to collectors.
"""

import threading
from dataclasses import dataclass

import boto3
import botocore.exceptions
from botocore.config import Config
from rich.console import Console

from .config import ProfileConfig

console = Console()

# Adaptive retry handles throttling (with client-side rate limiting) inside botocore,
# so collectors never need to sleep/retry or restart pagination themselves.
BOTO_CONFIG = Config(
    retries={"mode": "adaptive", "max_attempts": 10},
    connect_timeout=10,
    read_timeout=60,
    max_pool_connections=32,
)


class ClientFactory:
    """
    Thread-safe boto3 client provider for one account.

    boto3 ``Session`` objects are not thread-safe, but the clients they create are.
    Client creation is serialised behind a lock and each (service, region) client is
    created once and shared by every worker thread.
    """

    def __init__(self, session: boto3.Session, config: Config = BOTO_CONFIG):
        self._session = session
        self._config = config
        self._lock = threading.Lock()
        self._clients: dict[tuple[str, str], object] = {}

    def get(self, service: str, region: str):
        key = (service, region)
        client = self._clients.get(key)
        if client is not None:
            return client
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = self._session.client(service, region_name=region, config=self._config)
                self._clients[key] = client
            return client


@dataclass
class AccountInfo:
    """Resolved AWS account information."""

    account_id: str
    account_alias: str
    profile_name: str
    caller_arn: str


class SessionManager:
    """Manages boto3 sessions for SSO profiles."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._sessions: dict[str, boto3.Session] = {}
        self._factories: dict[str, ClientFactory] = {}
        self._account_info: dict[str, AccountInfo] = {}

    def create_session(self, profile: ProfileConfig, verbose: bool | None = None) -> boto3.Session | None:
        """
        Create a boto3 session for the given profile.
        Returns None if the SSO token is invalid/expired.
        """
        if profile.profile_name in self._sessions:
            return self._sessions[profile.profile_name]

        show_output = self.verbose if verbose is None else verbose

        try:
            session = boto3.Session(profile_name=profile.profile_name)
            factory = ClientFactory(session)
            # Validate the session by calling STS
            identity = factory.get("sts", profile.region or "us-east-1").get_caller_identity()

            account_id = identity["Account"]
            caller_arn = identity["Arn"]

            # Try to get account alias
            account_alias = account_id  # fallback
            try:
                aliases = factory.get("iam", "us-east-1").list_account_aliases().get("AccountAliases", [])
                if aliases:
                    account_alias = aliases[0]
            except Exception:
                pass  # Not all roles have iam:ListAccountAliases permission

            self._sessions[profile.profile_name] = session
            self._factories[profile.profile_name] = factory
            self._account_info[profile.profile_name] = AccountInfo(
                account_id=account_id,
                account_alias=account_alias,
                profile_name=profile.profile_name,
                caller_arn=caller_arn,
            )

            if show_output:
                console.print(
                    f"  [green]✅[/green] Profile [bold]{profile.profile_name}[/bold] → "
                    f"Account [cyan]{account_id}[/cyan] ({account_alias})"
                )
            return session

        except botocore.exceptions.UnauthorizedSSOTokenError:
            console.print(
                f"  [red]❌[/red] Profile [bold]{profile.profile_name}[/bold] → SSO token expired.\n"
                f"     [yellow]Run: aws sso login --profile {profile.profile_name}[/yellow]"
            )
            return None

        except botocore.exceptions.SSOTokenLoadError:
            console.print(
                f"  [red]❌[/red] Profile [bold]{profile.profile_name}[/bold] → SSO token not found.\n"
                f"     [yellow]Run: aws sso login --profile {profile.profile_name}[/yellow]"
            )
            return None

        except botocore.exceptions.ClientError as e:
            console.print(
                f"  [red]❌[/red] Profile [bold]{profile.profile_name}[/bold] → {e.response['Error']['Message']}"
            )
            return None

        except Exception as e:
            console.print(
                f"  [red]❌[/red] Profile [bold]{profile.profile_name}[/bold] → Unexpected error: {e}"
            )
            return None

    def get_session(self, profile_name: str) -> boto3.Session | None:
        """Get a cached session by profile name."""
        return self._sessions.get(profile_name)

    def get_factory(self, profile_name: str) -> ClientFactory | None:
        """Get the thread-safe client factory for a profile."""
        return self._factories.get(profile_name)

    def get_account_info(self, profile_name: str) -> AccountInfo | None:
        """Get account info for a profile."""
        return self._account_info.get(profile_name)
