"""Схема сведений об установке."""

from pydantic import BaseModel, Field


class InstallationRead(BaseModel):
    """Факты установки: одинаковы для любого запросившего и меняются только с её настройкой."""

    mcp_url: str = Field(
        examples=["http://localhost:8100/mcp"],
        description=(
            "Address an MCP client connects to, whole: scheme, host, port and path. Use it "
            "as is: it is set by the installation (`TRACKER_MCP_PUBLIC_URL`) and differs "
            "from the address of this API behind a proxy or on another machine. Unset, it "
            "is `http://localhost:<TRACKER_MCP_PORT><TRACKER_MCP_PATH>`, which is right for "
            "a client on the machine the installation runs on"
        ),
    )
