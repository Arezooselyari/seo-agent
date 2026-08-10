from __future__ import annotations

from supabase import Client

from ..config import Secrets
from ..llm_chat import ToolSpec
from . import consultation_status, lead_capture


def get_tool_specs(*, client: Client, tenant_id: int, conversation_id: int,
                   secrets: Secrets | None = None) -> list[ToolSpec]:
    return [
        ToolSpec(
            declaration=lead_capture.DECLARATION,
            execute=lead_capture.make_executor(
                client=client, tenant_id=tenant_id, conversation_id=conversation_id,
                secrets=secrets,
            ),
        ),
        ToolSpec(
            declaration=consultation_status.DECLARATION,
            execute=consultation_status.make_executor(client=client, tenant_id=tenant_id),
        ),
    ]
