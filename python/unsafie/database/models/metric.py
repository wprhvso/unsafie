from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (Index("ix_metrics_node_at", "node", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node: Mapped[str] = mapped_column(String(32))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
