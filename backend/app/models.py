from datetime import datetime, timezone
from decimal import Decimal


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Colonnes monétaires (montants HT/TVA/TTC des devis/factures, taux horaire) :
# NUMERIC(10, 2) plutôt que FLOAT — un flottant binaire ne peut pas représenter
# exactement la plupart des valeurs décimales (0.1 + 0.2 != 0.3 en binaire), ce
# qui peut faire dériver des totaux de quelques centimes après des additions
# répétées, ou casser des comparaisons d'égalité. NUMERIC stocke la valeur
# décimale exacte et SQLAlchemy la restitue en Decimal Python (voir
# app/helpers.py:to_money pour la conversion sûre depuis un float/form).
Money = Numeric(12, 2)


class Client(Base):
    __tablename__ = "client"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    interventions: Mapped[list["Intervention"]] = relationship(back_populates="client")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="client")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="client")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="client")


class Machine(Base):
    __tablename__ = "machine"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bios_serial: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    machine_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_intervention: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    interventions: Mapped[list["Intervention"]] = relationship(back_populates="machine")


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(80), default="technicien")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    # Double authentification (TOTP, compatible Google Authenticator/Authy) —
    # obligatoire pour le role admin, voir auth.py et main.py (routes /2fa/*).
    # totp_secret n'est renseigne qu'une fois l'enrolement confirme (un secret
    # genere mais jamais confirme reste dans le cookie temporaire de session,
    # jamais en base) ; totp_recovery_codes est une liste JSON de hachages
    # bcrypt a usage unique (perte du telephone).
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_recovery_codes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class Part(Base):
    __tablename__ = "part"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    part_type: Mapped[str] = mapped_column(String(80))
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capacity_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Intervention(Base):
    __tablename__ = "intervention"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id", ondelete="SET NULL"), nullable=True)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machine.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    machine_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bios_serial: Mapped[str | None] = mapped_column(String(255), nullable=True)
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_loss_risk: Mapped[str | None] = mapped_column(String(80), nullable=True)
    disk_risk: Mapped[str | None] = mapped_column(String(80), nullable=True)
    offline_windows: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(80), default="nouvelle")
    archive_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    labor_minutes: Mapped[int] = mapped_column(Integer, default=0)
    labor_rate: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.0"))
    signature_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    client: Mapped["Client | None"] = relationship(back_populates="interventions")
    machine: Mapped["Machine | None"] = relationship(back_populates="interventions")
    invoice: Mapped["Invoice | None"] = relationship(back_populates="intervention", uselist=False)
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="intervention")
    photos: Mapped[list["InterventionPhoto"]] = relationship(back_populates="intervention", cascade="all, delete-orphan")
    used_parts: Mapped[list["InterventionPart"]] = relationship(back_populates="intervention", cascade="all, delete-orphan")


class Quote(Base):
    __tablename__ = "quote"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[int | None] = mapped_column(ForeignKey("intervention.id", ondelete="SET NULL"), nullable=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id", ondelete="SET NULL"), nullable=True)
    quote_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.0"))
    total: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    intervention: Mapped["Intervention | None"] = relationship()
    client: Mapped["Client | None"] = relationship(back_populates="quotes")


class Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[int | None] = mapped_column(ForeignKey("intervention.id", ondelete="SET NULL"), nullable=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id", ondelete="SET NULL"), nullable=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quote.id", ondelete="SET NULL"), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.0"))
    total: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    # Lien de paiement Stripe Checkout (voir app/stripe_payments.py). Mis en
    # cache car une Session Stripe expire (~24h) : regeneree a la demande si
    # stripe_link_expires_at est depasse.
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_payment_link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stripe_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    intervention: Mapped["Intervention | None"] = relationship(back_populates="invoice")
    client: Mapped["Client | None"] = relationship(back_populates="invoices")


class Ticket(Base):
    __tablename__ = "ticket"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[int | None] = mapped_column(ForeignKey("intervention.id", ondelete="SET NULL"), nullable=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open")
    priority: Mapped[str] = mapped_column(String(50), default="medium")
    time_spent_minutes: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    intervention: Mapped["Intervention | None"] = relationship(back_populates="tickets")
    client: Mapped["Client | None"] = relationship(back_populates="tickets")


class InterventionPhoto(Base):
    __tablename__ = "intervention_photo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[int] = mapped_column(ForeignKey("intervention.id", ondelete="CASCADE"))
    phase: Mapped[str] = mapped_column(String(20), default="during")
    file_path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    intervention: Mapped["Intervention"] = relationship(back_populates="photos")


class InterventionPart(Base):
    __tablename__ = "intervention_part"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[int] = mapped_column(ForeignKey("intervention.id", ondelete="CASCADE"))
    # Pas de ondelete ici (RESTRICT implicite) : une pièce déjà utilisée dans
    # une intervention ne doit pas pouvoir être supprimée silencieusement (voir
    # delete_part dans routes/parts.py, qui intercepte l'IntegrityError pour
    # afficher un message clair plutôt qu'une erreur 500).
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    intervention: Mapped["Intervention"] = relationship(back_populates="used_parts")
    part: Mapped["Part"] = relationship()


class Reminder(Base):
    """Trace des relances envoyées pour un devis ou une facture en retard.

    target_type vaut "quote" ou "invoice" ; target_id référence Quote.id ou
    Invoice.id selon le cas (pas de FK unique possible sur deux tables).
    """
    __tablename__ = "reminder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    sent_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)


class Appointment(Base):
    __tablename__ = "appointment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id", ondelete="SET NULL"), nullable=True)
    intervention_id: Mapped[int | None] = mapped_column(ForeignKey("intervention.id", ondelete="SET NULL"), nullable=True)
    technician_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    client: Mapped["Client | None"] = relationship()
    intervention: Mapped["Intervention | None"] = relationship()
    technician: Mapped["User | None"] = relationship()


class ClientAccount(Base):
    """Compte de connexion à l'espace client — séparé de la fiche CRM `Client`.

    Un `Client` (fiche interne) peut avoir au plus un `ClientAccount` (accès portail).
    `hashed_password` est nullable : un compte peut n'utiliser que l'OAuth (Google/GitHub).
    """
    __tablename__ = "client_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("client.id", ondelete="CASCADE"), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    client: Mapped["Client"] = relationship()
    oauth_identities: Mapped[list["ClientOAuthIdentity"]] = relationship(back_populates="client_account", cascade="all, delete-orphan")


class ClientOAuthIdentity(Base):
    """Identité OAuth (Google/GitHub) liée à un ClientAccount existant.

    La liaison ne peut se faire qu'avec un compte déjà créé par l'atelier
    (email correspondant) — voir app/oauth.py et routes/client_portal.py.
    """
    __tablename__ = "client_oauth_identity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_account_id: Mapped[int] = mapped_column(ForeignKey("client_account.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    client_account: Mapped["ClientAccount"] = relationship(back_populates="oauth_identities")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_client_oauth_provider_user"),
    )


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
