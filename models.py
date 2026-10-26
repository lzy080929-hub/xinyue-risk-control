from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint

from extensions import db


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    """Return one unambiguous UTC representation for API responses."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ParticipantSession(db.Model):
    """One consented participation. The public code is not an access credential."""

    __tablename__ = "participant_sessions"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False)
    is_test = db.Column(db.Boolean, nullable=False, default=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="in_progress", index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)

    consent_version = db.Column(db.String(32), nullable=False)
    consented_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    experiment_version = db.Column(db.String(32), nullable=False)
    scale_version = db.Column(db.String(32), nullable=False)
    behavior_metrics_version = db.Column(db.String(32), nullable=False)
    client_context = db.Column(db.JSON, nullable=True)
    source = db.Column(db.String(64), nullable=True, index=True)
    terms_snapshot = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    submission_key = db.Column(db.String(64), unique=True, nullable=True)
    receipt_id = db.Column(db.String(36), unique=True, nullable=True)

    draft = db.relationship(
        "FormDraft",
        back_populates="participant",
        uselist=False,
        cascade="all, delete-orphan",
    )
    submission = db.relationship(
        "Submission",
        back_populates="participant",
        uselist=False,
        cascade="all, delete-orphan",
    )
    scale_answers = db.relationship(
        "ScaleAnswer",
        back_populates="participant",
        cascade="all, delete-orphan",
        order_by="ScaleAnswer.item_number",
    )
    behavior_batches = db.relationship(
        "BehaviorBatch",
        back_populates="participant",
        cascade="all, delete-orphan",
        order_by="BehaviorBatch.batch_seq",
    )
    behavior_summary = db.relationship(
        "BehaviorSummary",
        back_populates="participant",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('in_progress', 'submitted')",
            name="ck_participant_status",
        ),
        db.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_participant_progress",
        ),
    )

    @property
    def is_submitted(self) -> bool:
        return self.status == "submitted"

    def receipt_payload(self, *, already_submitted: bool) -> dict[str, object]:
        return {
            "participant_id": self.public_id,
            "status": self.status,
            "submitted_at": iso_utc(self.submitted_at),
            "receipt_id": self.receipt_id,
            "submission_key": self.submission_key,
            "already_submitted": already_submitted,
            "behavior_status": self.behavior_summary.status if self.behavior_summary else "not_started",
        }


class RrtInvitation(db.Model):
    """Eligibility/redemption only; contains no answer or response identifier."""
    __tablename__ = "rrt_invitations"
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey("participant_sessions.id"), unique=True, nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    protocol_version = db.Column(db.String(32), nullable=False)
    redeemed = db.Column(db.Boolean, nullable=False, default=False)


class RrtResponse(db.Model):
    """Mixed response only: no participant, voucher, random branch or exact time."""
    __tablename__ = "rrt_responses"
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    protocol_version = db.Column(db.String(32), nullable=False, index=True)
    is_test = db.Column(db.Boolean, nullable=False, index=True)
    batch_day = db.Column(db.Date, nullable=False)
    choice = db.Column(db.String(8), nullable=False)
    __table_args__ = (db.CheckConstraint("choice IN ('yes', 'no', 'skipped')", name="ck_rrt_choice"),)


class FormDraft(db.Model):
    """Latest autosaved snapshot. Final answers live in Submission."""

    __tablename__ = "form_drafts"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(
        db.Integer,
        db.ForeignKey("participant_sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    payload = db.Column(db.JSON, nullable=False)
    scale_payload = db.Column(db.JSON, nullable=True)
    client_seq = db.Column(db.Integer, nullable=False, default=0)
    server_revision = db.Column(db.Integer, nullable=False, default=1)
    saved_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    participant = db.relationship("ParticipantSession", back_populates="draft")


class Submission(db.Model):
    """Immutable final form snapshot created in the submit transaction."""

    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(
        db.Integer,
        db.ForeignKey("participant_sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    submission_key = db.Column(db.String(64), unique=True, nullable=False)
    receipt_id = db.Column(
        db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    payload = db.Column(db.JSON, nullable=False)
    content_hash = db.Column(db.String(64), nullable=False)
    form_version = db.Column(db.String(32), nullable=False)
    # Nullable so stage-one submissions remain valid historical records. New
    # stage-two submissions store an immutable scoring snapshot here.
    scale_version = db.Column(db.String(32), nullable=True)
    scoring_version = db.Column(db.String(32), nullable=True)
    scale_scores = db.Column(db.JSON, nullable=True)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    participant = db.relationship("ParticipantSession", back_populates="submission")


class ScaleAnswer(db.Model):
    """One raw survey answer per item. No missing value is converted to zero."""

    __tablename__ = "scale_answers"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(
        db.Integer,
        db.ForeignKey("participant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_number = db.Column(db.Integer, nullable=False)
    raw_score = db.Column(db.Integer, nullable=True)
    scored_score = db.Column(db.Integer, nullable=True)
    is_reverse = db.Column(db.Boolean, nullable=False, default=False)
    answered_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    participant = db.relationship("ParticipantSession", back_populates="scale_answers")

    __table_args__ = (
        UniqueConstraint(
            "participant_id", "item_number", name="uq_scale_answer_participant_item"
        ),
        db.CheckConstraint(
            "item_number >= 1 AND item_number <= 29", name="ck_scale_item_number"
        ),
        db.CheckConstraint(
            "raw_score IS NULL OR (raw_score >= 1 AND raw_score <= 7)",
            name="ck_scale_raw_score",
        ),
        db.CheckConstraint(
            "scored_score IS NULL OR (scored_score >= 1 AND scored_score <= 7)",
            name="ck_scale_scored_score",
        ),
    )


class BehaviorBatch(db.Model):
    """Incremental event batch. A batch is inserted at most once per session."""

    __tablename__ = "behavior_batches"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(
        db.Integer,
        db.ForeignKey("participant_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id = db.Column(db.String(64), nullable=False)
    batch_seq = db.Column(db.Integer, nullable=False)
    events = db.Column(db.JSON, nullable=False)
    event_count = db.Column(db.Integer, nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    participant = db.relationship("ParticipantSession", back_populates="behavior_batches")

    __table_args__ = (
        UniqueConstraint(
            "participant_id", "batch_id", name="uq_behavior_batch_participant_batch"
        ),
        UniqueConstraint(
            "participant_id", "batch_seq", name="uq_behavior_batch_participant_seq"
        ),
        db.CheckConstraint("batch_seq >= 1", name="ck_behavior_batch_seq"),
        db.CheckConstraint("event_count >= 0", name="ck_behavior_event_count"),
    )


class BehaviorSummary(db.Model):
    """Server-derived counts. It does not claim that behavior capture is complete."""

    __tablename__ = "behavior_summaries"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(
        db.Integer,
        db.ForeignKey("participant_sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    received_batches = db.Column(db.Integer, nullable=False, default=0)
    received_events = db.Column(db.Integer, nullable=False, default=0)
    last_batch_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(24), nullable=False, default="not_started")
    metrics = db.Column(db.JSON, nullable=True)
    expected_batches = db.Column(db.Integer, nullable=True)
    expected_events = db.Column(db.Integer, nullable=True)
    dropped_events = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    participant = db.relationship("ParticipantSession", back_populates="behavior_summary")
