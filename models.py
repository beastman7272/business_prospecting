from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Business(db.Model):
    __tablename__ = "businesses"

    id = db.Column(db.Integer, primary_key=True)
    place_id = db.Column(db.String, unique=True, nullable=False, index=True)
    name = db.Column(db.String, nullable=False)
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    formatted_address = db.Column(db.String)
    primary_type = db.Column(db.String)
    types = db.Column(db.Text)  # JSON string of types[]
    website = db.Column(db.String)
    phone = db.Column(db.String)
    status = db.Column(db.String, default="New", index=True)
    enriched = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    intel = db.relationship("Intel", back_populates="business", uselist=False)
    notes = db.relationship("Note", back_populates="business", cascade="all, delete")
    contacts = db.relationship(
        "Contact", back_populates="business", cascade="all, delete-orphan"
    )


class Intel(db.Model):
    __tablename__ = "intel"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), unique=True, nullable=False
    )
    company_summary = db.Column(db.Text)
    products_services = db.Column(db.Text)
    estimated_size = db.Column(db.Text)
    target_customers = db.Column(db.Text)
    key_contacts = db.Column(db.Text)
    technologies_used = db.Column(db.Text)
    recent_news = db.Column(db.Text)
    potential_pain_points = db.Column(db.Text)
    outreach_angle = db.Column(db.Text)
    raw_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    business = db.relationship("Business", back_populates="intel")


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id"), index=True)
    body = db.Column(db.Text, nullable=False)
    type = db.Column(db.String, default="note")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    business = db.relationship("Business", back_populates="notes")


class Contact(db.Model):
    """
    A Stage 2 discovered contact for a business. Mirrors
    contact_discovery.ContactCandidate (name/title/company/confidence/
    why_relevant/evidence) plus a persisted rank from the discovery run and a
    `selected` flag for the one a rep chose to deep-dive.

    Upserted by (business_id, lowercased name) so re-running discovery refreshes
    a contact's fields without orphaning an already-built dossier.
    """
    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    name = db.Column(db.String, nullable=False)
    title = db.Column(db.String)
    company = db.Column(db.String)
    confidence = db.Column(db.String, default="low")  # high | medium | low
    why_relevant = db.Column(db.Text)
    evidence = db.Column(db.Text)   # JSON list of {url, snippet, query}
    rank = db.Column(db.Integer, default=0, index=True)  # 0 = top of the run
    selected = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    business = db.relationship("Business", back_populates="contacts")
    dossier = db.relationship(
        "Dossier", back_populates="contact", uselist=False,
        cascade="all, delete-orphan",
    )


class Dossier(db.Model):
    """
    A Stage 3 deep-dive dossier for one contact. Mirrors
    contact_dossier.ContactDossier: the flattened gate verdict, plus the four
    provenance-carrying tracks stored as JSON, warnings, and the full
    dossier_to_dict() payload in `raw_json` for lossless inspection.
    """
    __tablename__ = "dossiers"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(
        db.Integer, db.ForeignKey("contacts.id"), unique=True, nullable=False
    )

    # Gate verdict (contact_dossier.GateVerdict)
    currency = db.Column(db.String)            # current | uncertain | likely_departed
    seniority_score = db.Column(db.Integer)
    worth_deepdive = db.Column(db.Boolean, default=False)
    rationale = db.Column(db.Text)
    currency_evidence = db.Column(db.Text)     # JSON

    # Tracks — each a JSON list of provenance-carrying records
    reach = db.Column(db.Text)                 # JSON list[ReachValue]
    background = db.Column(db.Text)            # JSON list[BackgroundFact]
    engagement = db.Column(db.Text)           # JSON list[EngagementItem]
    org_inferences = db.Column(db.Text)       # JSON list[OrgInference]

    warnings = db.Column(db.Text)             # JSON list[str]
    raw_json = db.Column(db.Text)             # full dossier_to_dict() payload
    generated_at = db.Column(db.String)       # ISO timestamp from the dossier
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contact = db.relationship("Contact", back_populates="dossier")
