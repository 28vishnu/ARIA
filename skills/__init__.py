from skills.manager import SkillManager
from skills.calculator import CalculatorSkill
from skills.profile import ProfileSkill
from skills.memory import MemorySkill
from skills.document import DocumentSkill

def create_default_skill_manager() -> SkillManager:
    manager = SkillManager()
    manager.register(CalculatorSkill())
    manager.register(ProfileSkill())
    manager.register(MemorySkill())
    manager.register(DocumentSkill())
    return manager
