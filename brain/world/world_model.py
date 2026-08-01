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

    # ---------------------------------------------------------
    # PEOPLE
    # ---------------------------------------------------------

    def add_person(self, name: str, data: Dict[str, Any]):

        self.people.setdefault(name, {})
        self.people[name].update(data)

    def get_person(self, name: str):

        return self.people.get(name)

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

        self.projects.setdefault(name, {})
        self.projects[name].update(data)

    def get_project(self, name: str):

        return self.projects.get(name)

    # ---------------------------------------------------------
    # DOCUMENTS
    # ---------------------------------------------------------

    def add_document(self, name: str, data: Dict[str, Any]):

        self.documents.setdefault(name, {})
        self.documents[name].update(data)

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

        self.events.setdefault(name, {})
        self.events[name].update(data)

    # ---------------------------------------------------------
    # GOALS
    # ---------------------------------------------------------

    def add_goal(self, name: str, data: Dict[str, Any]):

        self.goals.setdefault(name, {})
        self.goals[name].update(data)

    def get_goal(self, name: str):

        return self.goals.get(name)

    # ---------------------------------------------------------
    # PREFERENCES
    # ---------------------------------------------------------

    def add_preference(self, key: str, value):

        self.preferences[key] = value

    # ---------------------------------------------------------
    # TIMELINE
    # ---------------------------------------------------------

    def add_timeline_event(self, event):

        self.timeline.append(event)

    # ---------------------------------------------------------
    # GLOBAL CONTEXT
    # ---------------------------------------------------------

    def get_context(self):

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
            "timeline": self.timeline,
        }

    # ---------------------------------------------------------

    def snapshot(self):

        return self.get_context() 