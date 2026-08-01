import logging
from typing import Dict, Any

logger = logging.getLogger("aria")


class WorldModel:
    """
    ARIA's persistent understanding of the user's world.

    This is NOT memory.
    This is NOT vector search.

    It is a structured model of everything ARIA knows.
    """

    def __init__(self):

        self.people: Dict[str, Any] = {}
        self.organizations: Dict[str, Any] = {}
        self.projects: Dict[str, Any] = {}
        self.documents: Dict[str, Any] = {}
        self.places: Dict[str, Any] = {}
        self.devices: Dict[str, Any] = {}
        self.events: Dict[str, Any] = {}
        self.goals: Dict[str, Any] = {}
        self.preferences: Dict[str, Any] = {}
        self.timeline = []

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
        }

        self.statistics = {
            "people": 0,
            "projects": 0,
            "documents": 0,
            "goals": 0,
            "events": 0,
            "tasks": 0,
        }

    # ---------------------------------------------------------
    # PEOPLE
    # ---------------------------------------------------------

    def add_person(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.people
        self.people.setdefault(name, {})
        self.people[name].update(data)
        if is_new:
            self.statistics["people"] += 1

    def update_person(self, name: str, data: Dict[str, Any]):
        if name in self.people:
            self.people[name].update(data)
        else:
            self.add_person(name, data)

    def get_person(self, name: str):
        return self.people.get(name)

    def remove_person(self, name: str):
        if name in self.people:
            del self.people[name]
            self.statistics["people"] = max(0, self.statistics["people"] - 1)

    # ---------------------------------------------------------
    # ORGANIZATIONS
    # ---------------------------------------------------------

    def add_organization(self, name: str, data: Dict[str, Any]):
        self.organizations.setdefault(name, {})
        self.organizations[name].update(data)

    # ---------------------------------------------------------
    # PROJECTS
    # ---------------------------------------------------------

    def add_project(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.projects
        self.projects.setdefault(name, {})
        self.projects[name].update(data)
        if is_new:
            self.statistics["projects"] += 1

    def update_project(self, name: str, data: Dict[str, Any]):
        if name in self.projects:
            self.projects[name].update(data)
        else:
            self.add_project(name, data)

    def get_project(self, name: str):
        return self.projects.get(name)

    def remove_project(self, name: str):
        if name in self.projects:
            del self.projects[name]
            self.statistics["projects"] = max(0, self.statistics["projects"] - 1)

    # ---------------------------------------------------------
    # DOCUMENTS
    # ---------------------------------------------------------

    def add_document(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.documents
        self.documents.setdefault(name, {})
        self.documents[name].update(data)
        if is_new:
            self.statistics["documents"] += 1

    def update_document(self, name: str, data: Dict[str, Any]):
        if name in self.documents:
            self.documents[name].update(data)
        else:
            self.add_document(name, data)

    def remove_document(self, name: str):
        if name in self.documents:
            del self.documents[name]
            self.statistics["documents"] = max(0, self.statistics["documents"] - 1)

    # ---------------------------------------------------------
    # PLACES
    # ---------------------------------------------------------

    def add_place(self, name: str, data: Dict[str, Any]):
        self.places.setdefault(name, {})
        self.places[name].update(data)

    # ---------------------------------------------------------
    # DEVICES
    # ---------------------------------------------------------

    def add_device(self, name: str, data: Dict[str, Any]):
        self.devices.setdefault(name, {})
        self.devices[name].update(data)

    # ---------------------------------------------------------
    # EVENTS
    # ---------------------------------------------------------

    def add_event(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.events
        self.events.setdefault(name, {})
        self.events[name].update(data)
        if is_new:
            self.statistics["events"] += 1

    # ---------------------------------------------------------
    # GOALS
    # ---------------------------------------------------------

    def add_goal(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.goals
        self.goals.setdefault(name, {})
        self.goals[name].update(data)
        if is_new:
            self.statistics["goals"] += 1

    def update_goal(self, name: str, data: Dict[str, Any]):
        if name in self.goals:
            self.goals[name].update(data)
        else:
            self.add_goal(name, data)

    def get_goal(self, name: str):
        return self.goals.get(name)

    def remove_goal(self, name: str):
        if name in self.goals:
            del self.goals[name]
            self.statistics["goals"] = max(0, self.statistics["goals"] - 1)

    # ---------------------------------------------------------
    # PREFERENCES
    # ---------------------------------------------------------

    def add_preference(self, key: str, value):
        self.preferences[key] = value

    # ---------------------------------------------------------
    # ROUTINES & HABITS
    # ---------------------------------------------------------

    def add_routine(self, name: str, data: Dict[str, Any]):
        self.routines[name] = data

    def get_routine(self, name: str):
        return self.routines.get(name)

    # ---------------------------------------------------------
    # TASKS
    # ---------------------------------------------------------

    def add_task(self, name: str, data: Dict[str, Any]):
        is_new = name not in self.tasks
        self.tasks.setdefault(name, {})
        self.tasks[name].update(data)
        if is_new:
            self.statistics["tasks"] += 1

    def update_task(self, name: str, data: Dict[str, Any]):
        if name in self.tasks:
            self.tasks[name].update(data)
        else:
            self.add_task(name, data)

    def complete_task(self, name: str):
        if name in self.tasks:
            self.tasks[name]["completed"] = True

    def remove_task(self, name: str):
        if name in self.tasks:
            del self.tasks[name]
            self.statistics["tasks"] = max(0, self.statistics["tasks"] - 1)

    # ---------------------------------------------------------
    # ACTIVE SETTERS
    # ---------------------------------------------------------

    def set_active_project(self, project_name: str):
        self.active["project"] = project_name

    def set_active_document(self, document_name: str):
        self.active["document"] = document_name

    def set_active_goal(self, goal_name: str):
        self.active["goal"] = goal_name

    def set_active_task(self, task_name: str):
        self.active["task"] = task_name

    def clear_active(self):
        self.active = {
            "project": None,
            "document": None,
            "conversation": None,
            "goal": None,
            "task": None,
            "location": None,
        }

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    def search(self, query: str):
        q = query.lower()
        results = {
            "people": {k: v for k, v in self.people.items() if q in k.lower()},
            "projects": {k: v for k, v in self.projects.items() if q in k.lower()},
            "documents": {k: v for k, v in self.documents.items() if q in k.lower()},
            "goals": {k: v for k, v in self.goals.items() if q in k.lower()},
            "events": {k: v for k, v in self.events.items() if q in k.lower()},
            "tasks": {k: v for k, v in self.tasks.items() if q in k.lower()},
        }
        return results

    # ---------------------------------------------------------
    # TIMELINE
    # ---------------------------------------------------------

    def add_timeline_event(self, event):
        self.timeline.append(event)

    # ---------------------------------------------------------
    # GLOBAL CONTEXT & SNAPSHOT
    # ---------------------------------------------------------

    def get_context(self):
        return self.snapshot()

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
