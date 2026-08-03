import ast
import logging
from pathlib import Path

logger = logging.getLogger("aria")


class CodeParser:

    def parse(self, file_path):

        source = Path(file_path).read_text(
            encoding="utf-8",
            errors="ignore",
        )

        tree = ast.parse(source)

        result = {
            "file": Path(file_path).name,
            "classes": [],
            "functions": [],
            "imports": [],
        }

        for node in ast.walk(tree):

            if isinstance(node, ast.ClassDef):

                result["classes"].append({
                    "name": node.name,
                    "line": node.lineno,
                })

            elif isinstance(node, ast.FunctionDef):

                result["functions"].append({
                    "name": node.name,
                    "line": node.lineno,
                })

            elif isinstance(node, ast.AsyncFunctionDef):

                result["functions"].append({
                    "name": node.name,
                    "line": node.lineno,
                    "async": True,
                })

            elif isinstance(node, ast.Import):

                for alias in node.names:

                    result["imports"].append(alias.name)

            elif isinstance(node, ast.ImportFrom):

                module = node.module or ""

                result["imports"].append(module)

        logger.info(

            "[CodeParser] %s | %d classes | %d functions",

            result["file"],

            len(result["classes"]),

            len(result["functions"]),

        )

        return result
