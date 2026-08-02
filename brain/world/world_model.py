import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger("aria")


class WorldModel:
    """
    ARIA's persistent understanding of the user's world.

    This is NOT memory.
    This is NOT vector search.

    It is a structured model of everything ARIA knows.
    """

    def __init__(
        self,
        mongodb=None,
    ):
        self.mongodb = mongodb
        self.collection = None

        if mongodb is not None:
            self.collection = mongodb["world_model"]

        self.people: Dict[str, Any] = {}
        self.organizations: Dict[str, Any] = {}
        self.projects: Dict[str, Any] = {}
        self.documents: Dict[str, Any] = {}
        self.places: Dict[str, Any] = {}
        self.devices: Dict[str, Any] = {}
        self.events: Dict[str, Any] = {}
        self.goals: Dict[str, Any] = {}
        self.preferences: Dict[str, Any] = {}
        self.relationships: Dict[str, Any] = {}
        self.timeline = []

        self.predictions: Dict[str, Any] = {}
        self.active_goals: Dict[str, Any] = {}
        self.completed_goals: Dict[str, Any] = {}
        self.reasoning_history: List[Any] = []
        self.decision_history: List[Any] = []
        self.execution_history: List[Any] = []

        self.workflow_state = {
            "goal": None,
            "completed_tasks": [],
            "running_tasks": [],
            "failed_tasks": [],
            "remaining_tasks": [],
            "progress": 0,
            "eta": None,
        }

        self.active = {
            "project": None,
            "document": None,
            "conversation": None,
            "goal": None,
            "task": None,
            "location": None,
        }

        self.routines = {}
        self.habits = {}
        self.long_term_plans = {}
        self.tasks = {}
        self.user_skills = {}
        self.interests = {}

        self.session = {
            "current_topic": None,
            "last_question": None,
            "last_answer": None,
            "active_memory": None,
            "conversation_depth": "normal",
            "last_skill": None,
            "last_document": None,
            "last_memory": None,
            "reasoning_chain": [],
        }

        self.statistics = {
            "people": 0,
            "projects": 0,
            "documents": 0,
            "goals": 0,
            "events": 0,
            "tasks": 0,
            "relationships": 0,
            "preferences": 0,
            "routines": 0,
            "habits": 0,
            "interests": 0,
        }

    # ---------------------------------------------------------
    # PERSISTENCE & RECOVERY
    # ---------------------------------------------------------

    async def save(self):
        if self.collection is None:
            return

        doc = self.snapshot()
        doc["_id"] = "world_model"
        await self.collection.replace_one(
            {"_id": "world_model"},
            doc,
            upsert=True,
        )

    async def load(self):
        if self.collection is None:
            return

        doc = await self.collection.find_one({"_id": "world_model"})
        if not doc:
            return

        self.people = doc.get("people", {})
        self.organizations = doc.get("organizations", {})
        self.projects = doc.get("projects", {})
        self.documents = doc.get("documents", {})
        self.places = doc.get("places", {})
        self.devices = doc.get("devices", {})
        self.events = doc.get("events", {})
        self.goals = doc.get("goals", {})
        self.preferences = doc.get("preferences", {})
        self.relationships = doc.get("relationships", {})
        self.timeline = doc.get("timeline", [])
        self.predictions = doc.get("predictions", {})
        self.active_goals = doc.get("active_goals", {})
        self.completed_goals = doc.get("completed_goals", {})
        self.reasoning_history = doc.get("reasoning_history", [])
        self.decision_history = doc.get("decision_history", [])
        self.execution_history = doc.get("execution_history", [])
        self.workflow_state = doc.get("workflow_state", self.workflow_state)
        self.active = doc.get("active", self.active)
        self.routines = doc.get("routines", {})
        self.habits = doc.get("habits", {})
        self.long_term_plans = doc.get("long_term_plans", {})
        self.tasks = doc.get("tasks", {})
        self.user_skills = doc.get("skills", {})
        self.interests = doc.get("interests", {})
        self.session = doc.get("session", self.session)
        self.statistics = doc.get("statistics", self.statistics)

    async def rebuild(self):
        self.__init__(mongodb=self.mongodb)
        await self.load()

    # ---------------------------------------------------------
    # REASONING & DECISION TRACKING
    # ---------------------------------------------------------

    async def record_prediction(self, key: str, prediction_data: Any):
        self.predictions[key] = {
            "data": prediction_data,
            "timestamp": datetime.utcnow(),
        }
        await self.save()

    async def record_decision(self, decision_data: Any):
        entry = {
            "id": str(uuid4()),
            "decision": decision_data,
            "timestamp": datetime.utcnow(),
        }
        self.decision_history.append(entry)
        await self.save()

    async def record_reflection(self, reflection_data: Any):
        entry = {
            "id": str(uuid4()),
            "reflection": reflection_data,
            "timestamp": datetime.utcnow(),
        }
        self.reasoning_history.append(entry)
        await self.save()

    def get_decision_history(self) -> List[Any]:
        return self.decision_history

    # ---------------------------------------------------------
    # EXECUTION TRACKING (NEW METHODS)
    # ---------------------------------------------------------

    async def record_execution(self, report):
        self.execution_history.append(report)

        if len(self.execution_history) > 1000:
            self.execution_history.pop(0)

        await self.save()

    def execution_summary(self):
        total = len(self.execution_history)

        success = sum(
            1
            for r in self.execution_history
            if r.get("success")
        )

        failures = total - success

        avg = (
            sum(r["duration"] for r in self.execution_history)
            / total
            if total
            else 0
        )

        return {
            "total_tasks": total,
            "success_rate": success / total if total else 0,
            "failures": failures,
            "average_duration": avg,
        }

    # ---------------------------------------------------------
    # WORKFLOW STATE MANAGEMENT
    # ---------------------------------------------------------

    async def update_workflow_state(
        self,
        goal: Optional[str] = None,
        completed_tasks: Optional[List[str]] = None,
        running_tasks: Optional[List[str]] = None,
        failed_tasks: Optional[List[str]] = None,
        remaining_tasks: Optional[List[str]] = None,
        progress: Optional[int] = None,
        eta: Optional[Any] = None,
    ):
        if goal is not None:
            self.workflow_state["goal"] = goal
        if completed_tasks is not None:
            self.workflow_state["completed_tasks"] = completed_tasks
        if running_tasks is not None:
            self.workflow_state["running_tasks"] = running_tasks
        if failed_tasks is not None:
            self.workflow_state["failed_tasks"] = failed_tasks
        if remaining_tasks is not None:
            self.workflow_state["remaining_tasks"] = remaining_tasks
        if progress is not None:
            self.workflow_state["progress"] = progress
        if eta is not None:
            self.workflow_state["eta"] = eta

        await self.save()

    def get_workflow_state(self) -> Dict[str, Any]:
        return self.workflow_state

    # ---------------------------------------------------------
    # RELATIONSHIPS
    # ---------------------------------------------------------

    async def add_relationship(
        self,
        source: str,
        relation: str,
        target: str,
    ):
        rel_id = str(uuid4())
        self.relationships[rel_id] = {
            "id": rel_id,
            "source": source,
            "relation": relation,
            "target": target,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
        }
        self.statistics["relationships"] = len(self.relationships)
        await self.save()

    # ---------------------------------------------------------
    # PEOPLE
    # ---------------------------------------------------------

    async def add_person(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.people
        self.people.setdefault(name, {
            "id": str(uuid4()),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
        })
        self.people[name].update(data)
        self.people[name]["updated_at"] = datetime.utcnow()
        if is_new:
            self.statistics["people"] += 1
        await self.save()

    async def update_person(self, name: str, data: Dict[str, Any]):
        if name in self.people:
            self.people[name].update(data)
            self.people[name]["updated_at"] = datetime.utcnow()
            await self.save()
        else:
            await self.add_person(name, data)

    def get_person(self, name: str):
        person = self.people.get(name)
        if person:
            person["last_accessed"] = datetime.utcnow()
        return person

    async def remove_person(self, name: str):
        if name in self.people:
            del self.people[name]
            self.statistics["people"] = max(0, self.statistics["people"] - 1)
            await self.save()

    # ---------------------------------------------------------
    # ORGANIZATIONS
    # ---------------------------------------------------------

    async def add_organization(self, name: str, data: Dict[str, Any]):
        self.organizations.setdefault(name, {
            "id": str(uuid4()),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        self.organizations[name].update(data)
        self.organizations[name]["updated_at"] = datetime.utcnow()
        await self.save()

    # ---------------------------------------------------------
    # PROJECTS
    # ---------------------------------------------------------

    async def add_project(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.projects
        self.projects.setdefault(name, {
            "id": str(uuid4()),
            "priority": 50,
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
        })
        self.projects[name].update(data)
        self.projects[name]["updated_at"] = datetime.utcnow()
        if is_new:
            self.statistics["projects"] += 1
        await self.save()

    async def update_project(self, name: str, data: Dict[str, Any]):
        if name in self.projects:
            self.projects[name].update(data)
            self.projects[name]["updated_at"] = datetime.utcnow()
            await self.save()
        else:
            await self.add_project(name, data)

    def get_project(self, name: str):
        proj = self.projects.get(name)
        if proj:
            proj["last_accessed"] = datetime.utcnow()
        return proj

    async def remove_project(self, name: str):
        if name in self.projects:
            del self.projects[name]
            self.statistics["projects"] = max(0, self.statistics["projects"] - 1)
            await self.save()

    # ---------------------------------------------------------
    # DOCUMENTS
    # ---------------------------------------------------------

    async def add_document(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.documents
        self.documents.setdefault(name, {
            "id": str(uuid4()),
            "priority": 50,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
        })
        self.documents[name].update(data)
        self.documents[name]["updated_at"] = datetime.utcnow()
        if is_new:
            self.statistics["documents"] += 1
        await self.save()

    async def update_document(self, name: str, data: Dict[str, Any]):
        if name in self.documents:
            self.documents[name].update(data)
            self.documents[name]["updated_at"] = datetime.utcnow()
            await self.save()
        else:
            await self.add_document(name, data)

    async def remove_document(self, name: str):
        if name in self.documents:
            del self.documents[name]
            self.statistics["documents"] = max(0, self.statistics["documents"] - 1)
            await self.save()

    # ---------------------------------------------------------
    # PLACES
    # ---------------------------------------------------------

    async def add_place(self, name: str, data: Dict[str, Any]):
        self.places.setdefault(name, {
            "id": str(uuid4()),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        self.places[name].update(data)
        self.places[name]["updated_at"] = datetime.utcnow()
        await self.save()

    # ---------------------------------------------------------
    # DEVICES
    # ---------------------------------------------------------

    async def add_device(self, name: str, data: Dict[str, Any]):
        self.devices.setdefault(name, {
            "id": str(uuid4()),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        self.devices[name].update(data)
        self.devices[name]["updated_at"] = datetime.utcnow()
        await self.save()

    # ---------------------------------------------------------
    # EVENTS
    # ---------------------------------------------------------

    async def add_event(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.events
        self.events.setdefault(name, {
            "id": str(uuid4()),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
        self.events[name].update(data)
        self.events[name]["updated_at"] = datetime.utcnow()
        if is_new:
            self.statistics["events"] += 1
        await self.save()

    # ---------------------------------------------------------
    # GOALS
    # ---------------------------------------------------------

    async def add_goal(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.goals
        self.goals.setdefault(name, {
            "id": str(uuid4()),
            "priority": 50,
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
        })
        self.goals[name].update(data)
        self.goals[name]["updated_at"] = datetime.utcnow()
        if is_new:
            self.statistics["goals"] += 1
        await self.save()

    async def update_goal(self, name: str, data: Dict[str, Any]):
        if name in self.goals:
            self.goals[name].update(data)
            self.goals[name]["updated_at"] = datetime.utcnow()
            await self.save()
        else:
            await self.add_goal(name, data)

    def get_goal(self, name: str):
        goal = self.goals.get(name)
        if goal:
            goal["last_accessed"] = datetime.utcnow()
        return goal

    async def remove_goal(self, name: str):
        if name in self.goals:
            del self.goals[name]
            self.statistics["goals"] = max(0, self.statistics["goals"] - 1)
            await self.save()

    # ---------------------------------------------------------
    # PREFERENCES
    # ---------------------------------------------------------

    async def add_preference(self, key: str, value):
        self.preferences[key] = value
        self.statistics["preferences"] = len(self.preferences)
        await self.save()

    # ---------------------------------------------------------
    # ROUTINES & HABITS
    # ---------------------------------------------------------

    async def add_routine(self, name: str, data: Dict[str, Any]):
        self.routines[name] = data
        self.statistics["routines"] = len(self.routines)
        await self.save()

    def get_routine(self, name: str):
        return self.routines.get(name)

    # ---------------------------------------------------------
    # TASKS
    # ---------------------------------------------------------

    async def add_task(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.tasks
        self.tasks.setdefault(name, {
            "id": str(uuid4()),
            "priority": 50,
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
        })
        self.tasks[name].update(data)
        self.tasks[name]["updated_at"] = datetime.utcnow()
        if is_new:
            self.statistics["tasks"] += 1
        await self.save()

    async def update_task(self, name: str, data: Dict[str, Any]):
        if name in self.tasks:
            self.tasks[name].update(data)
            self.tasks[name]["updated_at"] = datetime.utcnow()
            await self.save()
        else:
            await self.add_task(name, data)

    async def complete_task(self, name: str):
        if name in self.tasks:
            self.tasks[name]["completed"] = True
            self.tasks[name]["status"] = "completed"
            self.tasks[name]["updated_at"] = datetime.utcnow()
            await self.save()

    async def remove_task(self, name: str):
        if name in self.tasks:
            del self.tasks[name]
            self.statistics["tasks"] = max(0, self.statistics["tasks"] - 1)
            await self.save()

    # ---------------------------------------------------------
    # ACTIVE SETTERS
    # ---------------------------------------------------------

    async def set_active_project(self, project_name: str):
        self.active["project"] = project_name
        await self.save()

    async def set_active_document(self, document_name: str):
        self.active["document"] = document_name
        await self.save()

    async def set_active_goal(self, goal_name: str):
        self.active["goal"] = goal_name
        await self.save()

    async def set_active_task(self, task_name: str):
        self.active["task"] = task_name
        await self.save()

    async def clear_active(self):
        self.active = {
            "project": None,
            "document": None,
            "conversation": None,
            "goal": None,
            "task": None,
            "location": None,
        }
        await self.save()

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    def search(self, query: str):
        q = query.lower()

        def matches(item):
            if isinstance(item, dict):
                return any(q in str(v).lower() for v in item.values())
            return q in str(item).lower()

        results = {
            "people": {k: v for k, v in self.people.items() if q in k.lower() or matches(v)},
            "projects": {k: v for k, v in self.projects.items() if q in k.lower() or matches(v)},
            "documents": {k: v for k, v in self.documents.items() if q in k.lower() or matches(v)},
            "goals": {k: v for k, v in self.goals.items() if q in k.lower() or matches(v)},
            "events": {k: v for k, v in self.events.items() if q in k.lower() or matches(v)},
            "tasks": {k: v for k, v in self.tasks.items() if q in k.lower() or matches(v)},
        }
        return results

    # ---------------------------------------------------------
    # TIMELINE
    # ---------------------------------------------------------

    async def add_timeline_event(self, event):
        self.timeline.append(event)
        await self.save()

    # ---------------------------------------------------------
    # GLOBAL CONTEXT & SNAPSHOT
    # ---------------------------------------------------------

    def get_context(self):
        return self.snapshot()

    def summary(self):
        return {
            "people": len(self.people),
            "projects": len(self.projects),
            "tasks": len(self.tasks),
            "goals": len(self.goals),
            "relationships": len(self.relationships),
            "timeline_events": len(self.timeline),
        }

    def snapshot(self):
        return {
            "people": self.people,
            "organizations": self.organizations,
            "projects": self.projects,
            "documents": self.documents,
            "places": self.places,
            "devices": self.devices,
            "events": self.events,
            "goals": self.goals,
            "preferences": self.preferences,
            "relationships": self.relationships,
            "predictions": self.predictions,
            "active_goals": self.active_goals,
            "completed_goals": self.completed_goals,
            "reasoning_history": self.reasoning_history,
            "decision_history": self.decision_history,
            "execution_history": self.execution_history,
            "workflow_state": self.workflow_state,
            "tasks": self.tasks,
            "habits": self.habits,
            "routines": self.routines,
            "skills": self.user_skills,
            "interests": self.interests,
            "session": self.session,
            "active": self.active,
            "timeline": self.timeline,
            "statistics": self.statistics,
        }
