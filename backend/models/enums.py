from enum import Enum


class UserRole(str, Enum):
    educator = "educator"
    admin = "admin"
    internal = "internal"


class GSTCycle(str, Enum):
    quarterly = "quarterly"
    annual = "annual"
    none = "none"


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    complete = "complete"


class TaskSource(str, Enum):
    internal_crm = "internal_crm"
    luna = "luna"
    system = "system"


class KBClassification(str, Enum):
    exclusive_a = "Exclusive A"
    exclusive_b = "Exclusive B"
    problem = "Problem"
    special = "Special"
