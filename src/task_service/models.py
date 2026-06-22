from sqlalchemy import Column, String, Text, Numeric, Enum, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum

from shared.database import Base

class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid = True) , primary_key = True , default = uuid.uuid4)
    owner_email = Column(String, index = True , nullable = False)
    name = Column(Text, nullable = False)
    deadline = Column(TIMESTAMP(timezone = True) , nullable = False)
    weight_pct = Column(Numeric(5 , 2), nullable = False)
    difficulty = Column(Enum(Difficulty) , nullable = False)
    estimated_hours = Column(Numeric(6 , 2) , nullable = False)
    status = Column(String , nullable = False , server_default = "open")
    created_at =  Column(TIMESTAMP(timezone = True) , nullable = False , server_default = "now")
    updated_at =  Column(TIMESTAMP(timezone = True) , nullable = False , server_default = "now")

