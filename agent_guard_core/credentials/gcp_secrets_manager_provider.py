import json
from typing import Dict, Optional

from google.cloud import secretmanager
from google.api_core.exceptions import NotFound, AlreadyExists

from .secrets_provider import BaseSecretsProvider, SecretProviderException

DEFAULT_PROJECT_ID = "default"
DEFAULT_SECRET_ID = "agentic_env_vars"

class GCPSecretsProvider(BaseSecretsProvider):
    """
    Manages storing and retrieving secrets from Google Cloud Secret Manager.
    """

    def __init__(self,
                 project_id: str = DEFAULT_PROJECT_ID,
                 secret_id: str = DEFAULT_SECRET_ID):
        """
        Initializes the GCP Secret Manager client with the specified project ID.

        :param project_id: GCP project ID where the secrets are stored.
        :param secret_id: The ID of the secret to store/retrieve. Defaults to 'agentic_env_vars'.
        """
        super().__init__()
        self._project_id = project_id
        self._secret_id = secret_id
        self._parent = f"projects/{self._project_id}"
        self._client = None

    def connect(self) -> bool:
        """
        Establishes a connection to the GCP Secret Manager service.

        :return: True if connection is successful, raises SecretProviderException otherwise.
        """
        if self._client:
            return True
        try:
            self._client = secretmanager.SecretManagerServiceClient()
            return True
        except Exception as e:
            self.logger.error(
                "Error initializing GCP Secrets Manager client: %s", e.args[0])
            raise SecretProviderException(
                message=
                "Error connecting to the secret provider: GCPSecretsProvider with this exception: %s"
                % e.args[0])

    def _secret_path(self) -> str:
        """
        Returns the full path to the secret in GCP Secret Manager.
        """
        return f"{self._parent}/secrets/{self._secret_id}"

    def get_secret_dictionary(self) -> Dict[str, str]:
        """
        Retrieves the secret dictionary from GCP Secret Manager.

        :return: A dictionary containing the secrets.
        :raises SecretProviderException: If there is an error retrieving the secrets.
        """
        try:
            self.connect()
            version_name = f"{self._secret_path()}/versions/latest"
            response = self._client.access_secret_version(name=version_name)
            secret_text = response.payload.data.decode("UTF-8")
            return json.loads(secret_text)
        except NotFound:
            self.logger.warning("Secret not found: %s", self._secret_id)
        except Exception as e:
            raise SecretProviderException(str(e))
        return {}

    def store_secret_dictionary(self, secret_dictionary: Dict):
        """
        Stores the secret dictionary in GCP Secret Manager.
        
        :param secret_dictionary: The dictionary containing secrets to store.
        :raises SecretProviderException: If there is an error storing the secrets.
        """
        if secret_dictionary is None:
            raise SecretProviderException("Dictionary not provided")

        try:
            self.connect()
            secret_text = json.dumps(secret_dictionary)

            # Try to create the secret if it doesn't exist
            try:
                self._client.create_secret(
                    parent=self._parent,
                    secret_id=self._secret_id,
                    secret={
                        "replication": {
                            "automatic": {}
                        }
                    }
                )
            except AlreadyExists:
                pass  # Secret already exists, continue

            # Add a new version of the secret
            self._client.add_secret_version(
                parent=self._secret_path(),
                payload={"data": secret_text.encode("UTF-8")}
            )
        except Exception as e:
            self.logger.error("Error storing secret: %s", e)
            raise SecretProviderException("Error storing secret: %s" % e)

    def store(self, key: str, secret: str) -> None:
        """
        Stores a secret in GCP Secret Manager. Creates or updates the secret.
        
        :param key: The name of the secret.
        :param secret: The secret value to store.
        :raises SecretProviderException: If key or secret is missing, or if there is an error storing the secret.

        Caution:
        Concurrent access to secrets can cause issues. If two clients simultaneously list, update different environment variables,
        and then store, one client's updates may override the other's if they are working on the same secret.
        This issue will be addressed in future versions.
        """
        if not key or not secret:
            message = "store: key or secret is missing"
            self.logger.warning(message)
            raise SecretProviderException(message)

        dictionary = self.get_secret_dictionary()
        if not dictionary:
            dictionary = {}
            
        dictionary[key] = secret
        self.store_secret_dictionary(dictionary)

    def get(self, key: str) -> Optional[str]:
        """
        Retrieves a secret from GCP Secret Manager by key.

        :param key: The name of the secret to retrieve.
        :return: The secret value if retrieval is successful, None otherwise.
        :raises SecretProviderException: If there is an error retrieving the secret.
        """
        if not key:
            self.logger.warning("get: key is missing, proceeding with default")

        dictionary = self.get_secret_dictionary()
        return dictionary.get(key) if dictionary else None

    def delete(self, key: str) -> None:
        """
        Deletes a secret from GCP Secret Manager by key.

        :param key: The name of the secret to delete.
        :raises SecretProviderException: If key is missing or if there is an error deleting the secret.
        """
        if not key:
            message = "delete secret failed, key is none or empty"
            self.logger.warning(message)
            raise SecretProviderException(message)

        dictionary = self.get_secret_dictionary()
        if dictionary and key in dictionary:
            del dictionary[key]
            self.store_secret_dictionary(dictionary)
