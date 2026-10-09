"""流程说明版本。只有预先存在的当前在发布版本，没有审核发布入口。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from schema import (
    FLOW_BOUNDARY,
    FLOW_KEY,
    FLOW_LABEL,
    FLOW_STEPS,
    FLOW_TITLE,
    ProcedureVersion,
)


def seed_current(db: Session) -> ProcedureVersion:
    row = db.scalar(
        select(ProcedureVersion).where(
            ProcedureVersion.flow_key == FLOW_KEY,
            ProcedureVersion.current_published.is_(True),
        )
    )
    if row is not None:
        return row
    row = ProcedureVersion(
        version_id="flow-app-service-placeholder",
        flow_key=FLOW_KEY,
        version_label=FLOW_LABEL,
        title=FLOW_TITLE,
        steps=FLOW_STEPS,
        boundary=FLOW_BOUNDARY,
        current_published=True,
        withdrawn=False,
    )
    db.add(row)
    db.flush()
    return row


def lock_current(db: Session, flow_key: str) -> ProcedureVersion | None:
    return db.scalar(
        select(ProcedureVersion)
        .where(
            ProcedureVersion.flow_key == flow_key,
            ProcedureVersion.current_published.is_(True),
        )
        .with_for_update()
    )


def read_current(db: Session, flow_key: str) -> ProcedureVersion | None:
    return db.scalar(
        select(ProcedureVersion).where(
            ProcedureVersion.flow_key == flow_key,
            ProcedureVersion.current_published.is_(True),
        )
    )


def matches(row: ProcedureVersion, run) -> bool:
    return (
        row.version_id == run.cited_version_id
        and row.current_published
        and not row.withdrawn
        and row.title == run.title
        and row.steps == run.steps
        and row.boundary == run.boundary
        and row.version_label == run.version_label
        and row.flow_key == "App预约保养步骤"
    )
