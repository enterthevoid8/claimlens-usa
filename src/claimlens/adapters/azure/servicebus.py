"""Service Bus queue adapter. Messages carry ids only. Poison messages go to the dead-letter sub-queue."""

from __future__ import annotations

from typing import Any

from claimlens.adapters.azure.credentials import credential
from claimlens.adapters.ports import ReceivedJob
from claimlens.domain.models import ClaimJob


class ServiceBusJobQueue:
    def __init__(
        self, namespace: str, queue: str, client: Any | None = None, max_wait_s: int = 5
    ) -> None:
        if client is None:
            from azure.servicebus import ServiceBusClient

            client = ServiceBusClient(namespace, credential=credential())
        self.client = client
        self.queue = queue
        self.max_wait_s = max_wait_s
        self._receiver: Any | None = None

    def _get_receiver(self) -> Any:
        if self._receiver is None:
            self._receiver = self.client.get_queue_receiver(
                queue_name=self.queue, max_wait_time=self.max_wait_s
            )
        return self._receiver

    def send(self, job: ClaimJob) -> None:
        from azure.servicebus import ServiceBusMessage

        with self.client.get_queue_sender(queue_name=self.queue) as sender:
            sender.send_messages(
                ServiceBusMessage(
                    job.model_dump_json(),
                    content_type="application/json",
                    message_id=f"{job.claim_id}:{job.attempt}",
                )
            )

    def receive(self, max_messages: int = 1) -> list[ReceivedJob]:
        msgs = self._get_receiver().receive_messages(
            max_message_count=max_messages, max_wait_time=self.max_wait_s
        )
        out: list[ReceivedJob] = []
        for m in msgs:
            body = (
                b"".join(m.body)
                if hasattr(m.body, "__iter__") and not isinstance(m.body, (bytes, str))
                else m.body
            )
            job = ClaimJob.model_validate_json(body)
            out.append(
                ReceivedJob(
                    job=job,
                    receipt=str(m.message_id),
                    delivery_count=int(m.delivery_count or 0) + 1,
                    handle=m,
                )
            )
        return out

    def complete(self, received: ReceivedJob) -> None:
        self._get_receiver().complete_message(received.handle)

    def abandon(self, received: ReceivedJob) -> None:
        self._get_receiver().abandon_message(received.handle)

    def dead_letter(self, received: ReceivedJob, reason: str) -> None:
        self._get_receiver().dead_letter_message(
            received.handle, reason="processing_failed", error_description=reason[:1000]
        )
