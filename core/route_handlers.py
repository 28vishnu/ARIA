class GreetingHandler:

    async def handle(self, text, context):
        return None


class DocumentHandler:

    async def handle(self, text, context):
        return None


class VisionHandler:

    async def handle(self, text, context):
        """
        Execute vision analysis when image data is supplied
        through the cognitive routing context.

        Expected context:
            image_bytes: raw image bytes
            file_name: optional image filename
            prompt: optional vision instruction
            vision_engine: VisionEngine instance
        """

        context = context or {}

        image_bytes = context.get("image_bytes")

        if not image_bytes:
            return {
                "success": False,
                "text": "",
                "description": (
                    "Vision request received, but no image data "
                    "was supplied."
                ),
                "entities": [],
                "metadata": {},
            }

        vision_engine = context.get("vision_engine")

        if vision_engine is None:
            app_state = context.get("app_state")

            if app_state is not None:
                vision_engine = getattr(
                    app_state,
                    "vision_engine",
                    None,
                )

        if vision_engine is None:
            return {
                "success": False,
                "text": "",
                "description": (
                    "Vision engine is not available."
                ),
                "entities": [],
                "metadata": {},
            }

        file_name = context.get(
            "file_name",
            "image.jpg",
        )

        prompt = context.get(
            "prompt",
            (
                "Perform deep OCR and describe all visible "
                "text, layout, objects, people, charts, "
                "and visual contents in detail."
            ),
        )

        result = await vision_engine.analyze_visual(
            image_bytes=image_bytes,
            file_name=file_name,
            prompt=prompt,
        )

        return result


class ToolHandler:

    async def handle(self, text, context):
        return None


class PlannerHandler:

    async def handle(self, text, context):
        return None