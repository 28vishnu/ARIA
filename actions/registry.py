from actions.manager import ActionManager
from actions.actions.file import FileAction
from actions.actions.notification import NotificationAction
from actions.actions.time import TimeAction


def create_default_action_manager() -> ActionManager:
    manager = ActionManager(permission_mode="autonomous")

    manager.register(FileAction())
    manager.register(NotificationAction())
    manager.register(TimeAction())

    return manager
