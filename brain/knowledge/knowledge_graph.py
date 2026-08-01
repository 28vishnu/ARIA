import logging
from collections import defaultdict
from typing import Dict, List, Set

logger = logging.getLogger("aria")


class KnowledgeGraph:
    """
    ARIA's structured knowledge graph.

    Stores relationships such as:

    Saketh --studies_at--> GVP
    Japan --capital--> Tokyo
    Monday --class--> CN
    CN --faculty--> Arun Kumar

    Retrieval is deterministic and requires no LLM.
    """

    def __init__(self):

        # subject -> relation -> set(objects)

        self.graph = defaultdict(
            lambda: defaultdict(set)
        )

        # reverse lookup

        self.reverse_graph = defaultdict(
            lambda: defaultdict(set)
        )

    ############################################################

    async def add_fact(
        self,
        subject: str,
        relation: str,
        obj: str,
    ):

        if not subject or not relation or not obj:
            return

        subject = subject.strip()
        relation = relation.strip().lower()
        obj = obj.strip()

        self.graph[subject][relation].add(obj)

        self.reverse_graph[obj][relation].add(subject)

        logger.info(
            "[KnowledgeGraph] %s --%s--> %s",
            subject,
            relation,
            obj,
        )

    ############################################################

    async def search(
        self,
        query: str,
    ):

        query = query.lower()

        results = []

        # Search subject

        for subject, relations in self.graph.items():

            if query in subject.lower():

                for relation, objects in relations.items():

                    for obj in objects:

                        results.append(
                            {
                                "subject": subject,
                                "relation": relation,
                                "object": obj,
                            }
                        )

        # Search object

        for obj, relations in self.reverse_graph.items():

            if query in obj.lower():

                for relation, subjects in relations.items():

                    for subject in subjects:

                        results.append(
                            {
                                "subject": subject,
                                "relation": relation,
                                "object": obj,
                            }
                        )

        return results

    ############################################################

    async def related(
        self,
        subject,
        relation=None,
    ):

        if subject not in self.graph:
            return []

        if relation:

            return list(

                self.graph[subject].get(
                    relation,
                    []
                )

            )

        output = []

        for rel, objs in self.graph[subject].items():

            for obj in objs:

                output.append(

                    {

                        "relation": rel,

                        "object": obj,

                    }

                )

        return output

    ############################################################

    async def has_fact(
        self,
        subject,
        relation,
        obj,
    ):

        return (

            obj in

            self.graph

            .get(subject, {})

            .get(relation, set())

        )

    ############################################################

    async def delete_fact(
        self,
        subject,
        relation,
        obj,
    ):

        try:

            self.graph[subject][relation].remove(obj)

            self.reverse_graph[obj][relation].remove(subject)

            return True

        except Exception:

            return False

    ############################################################

    async def all_facts(self):

        facts = []

        for subject in self.graph:

            for relation in self.graph[subject]:

                for obj in self.graph[subject][relation]:

                    facts.append(

                        {

                            "subject": subject,

                            "relation": relation,

                            "object": obj,

                        }

                    )

        return facts

    ############################################################

    async def clear(self):

        self.graph.clear()

        self.reverse_graph.clear()

        logger.info(
            "[KnowledgeGraph] Cleared."
        )