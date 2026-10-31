from __future__ import annotations

from typing import Any

from claimlens.adapters.azure.credentials import credential


class AzureBlobStore:
    def __init__(self, account_url: str, container: str, client: Any | None = None) -> None:
        if client is None:
            from azure.storage.blob import BlobServiceClient

            client = BlobServiceClient(
                account_url=account_url, credential=credential()
            ).get_container_client(container)
        self.container = client

    def put(self, path: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self.container.upload_blob(
            name=path,
            data=data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def get(self, path: str) -> bytes:
        return bytes(self.container.download_blob(path).readall())

    def delete_prefix(self, prefix: str) -> int:
        n = 0
        for blob in self.container.list_blobs(name_starts_with=prefix.rstrip("/") + "/"):
            self.container.delete_blob(blob.name)
            n += 1
        return n

    def download_prefix(self, prefix: str, target: Any) -> int:
        """Used to fetch a model bundle: copies every blob under ``prefix`` into the directory ``target``."""
        from pathlib import Path

        n = 0
        for blob in self.container.list_blobs(name_starts_with=prefix.rstrip("/") + "/"):
            rel = blob.name[len(prefix.rstrip("/")) + 1 :]
            dest = (Path(target) / rel).resolve()
            if Path(target).resolve() not in dest.parents:
                raise ValueError("blob name escapes the target directory")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.get(blob.name))
            n += 1
        return n
