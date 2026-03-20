from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class Deadline(SQLModel, table=True):
    __tablename__ = "deadline"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True, unique=True)
    description: Optional[str] = Field(default=None)
    due_date: datetime = Field()  # stored as UTC
    created_by: int = Field()  # Discord user ID
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # TODO: populated by calendar sync once implemented; set to "SYNC_FAILED"
    # if the sync attempt fails so a retry can be triggered later.
    outlook_event_id: Optional[str] = Field(default=None)

    members: List["DeadlineMember"] = Relationship(
        back_populates="deadline",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class DeadlineMember(SQLModel, table=True):
    __tablename__ = "deadline_member"

    deadline_id: int = Field(
        foreign_key="deadline.id",
        primary_key=True,
    )
    user_id: int = Field(primary_key=True)  # Discord user ID

    deadline: Optional[Deadline] = Relationship(back_populates="members")
