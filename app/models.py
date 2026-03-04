from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class Installation(Base):
    __tablename__ = "installations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    github_installation_id = Column(Integer, unique=True, nullable=False, index=True)
    owner = Column(String, nullable=False)
    plan = Column(String, default="basic")  # "basic" or "pro"
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    installation_id = Column(Integer, ForeignKey("installations.id"), nullable=False)
    dodo_payment_id = Column(String, unique=True, nullable=True)
    status = Column(String, default="inactive")  # "active", "inactive", "cancelled"
    plan = Column(String, default="basic")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    installation_id = Column(Integer, ForeignKey("installations.id"), nullable=False)
    repo_full_name = Column(String, nullable=False)
    pr_number = Column(Integer, nullable=False)
    risk_level = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
