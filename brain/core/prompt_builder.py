class PromptBuilder:

    def build(
        self,
        decision,
        system_prompt: str,
    ) -> str:

        prompt = system_prompt

        # ---------- Tone ----------
        if decision.tone == "teacher":

            prompt += (
                "\n\n"
                "Explain concepts gradually."
                " Use examples."
                " Assume the user is learning."
            )

        elif decision.tone == "technical":

            prompt += (
                "\n\n"
                "Use technical terminology."
                " Avoid oversimplification."
            )

        elif decision.tone == "supportive":

            prompt += (
                "\n\n"
                "Be calm."
                " Help solve one step at a time."
            )

        elif decision.tone == "collaborative":

            prompt += (
                "\n\n"
                "Act like an engineering partner."
                " Brainstorm naturally."
            )

        # ---------- Detail ----------

        if decision.detail_level == "short":

            prompt += (
                "\n\n"
                "Keep the answer concise."
            )

        elif decision.detail_level == "detailed":

            prompt += (
                "\n\n"
                "Give a comprehensive explanation."
            )

        # ---------- Teaching ----------

        if decision.teaching_mode:

            prompt += (
                "\n\n"
                "Teach rather than simply answer."
            )

        return prompt